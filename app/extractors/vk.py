import os
import time
import threading
import logging
import asyncio
import yt_dlp

from .base import VideoExtractor
from typing import Optional, Dict, Any, Tuple

# Krátky cache znižuje počet volaní yt-dlp pri opakovaných requestoch; stále relatívne čerstvé linky.
_VK_PLAYBACK_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_VK_CACHE_LOCK = threading.Lock()
VK_PLAYBACK_CACHE_TTL = float(os.environ.get("VK_PLAYBACK_CACHE_TTL", "300"))
VK_PLAYBACK_RETRIES = int(os.environ.get("VK_PLAYBACK_RETRIES", "3"))
VK_PLAYBACK_RETRY_DELAY = float(os.environ.get("VK_PLAYBACK_RETRY_DELAY", "0.8"))

class VKExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "VK"

    def can_handle(self, url: str) -> bool:
        return any(domain in url.lower() for domain in ['vk.com', 'vk.video', 'vkvideo.ru', 'vkvideo.net', 'vkvideo.com', 'vk.ru', 'okcdn.ru'])

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract VK video metadata.
        Note: We store the VK page URL, not the direct stream URL (which expires).
        Stream URLs are extracted on-demand via the streaming endpoint.
        """
        return await asyncio.to_thread(self._extract_ytdlp, url)

    def _extract_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        # Better User-Agent to avoid 'registered users' block on some public videos
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': False,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'ignoreerrors': True,
            'no_warnings': True,
            'user_agent': user_agent,
            'http_headers': {
                'User-Agent': user_agent,
                'Referer': 'https://vk.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5'
            }
        }
        
        # Try to use cookies if available
        if os.path.exists("vk.netscape.txt"):
            ydl_opts['cookiefile'] = "vk.netscape.txt"
        elif os.path.exists("cookies.netscape.txt"):
            ydl_opts['cookiefile'] = "cookies.netscape.txt"
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                # Get best format - prefer MP4 over HLS to avoid .ts segment issues
                formats = info.get('formats', [])
                best_format = None
                max_height = 0
                
                # First pass: try to find best MP4 format
                for f in formats:
                    if not f.get('url'):
                        continue
                    # Skip HLS formats in first pass
                    if '.m3u8' in f.get('url', ''):
                        continue
                    height = f.get('height') or 0
                    if height > max_height:
                        max_height = height
                        best_format = f
                
                # Second pass: if no MP4 found, accept HLS
                if not best_format:
                    max_height = 0
                    for f in formats:
                        if not f.get('url'):
                            continue
                        height = f.get('height') or 0
                        if height > max_height:
                            max_height = height
                            best_format = f

                # Fallback to info URL if no formats
                stream_url = best_format['url'] if best_format else info.get('url')
                
                # Smarter HLS detection using protocol and URL content
                protocol = (best_format.get('protocol') or '').lower() if best_format else ''
                is_hls = 'm3u8' in protocol or '.m3u8' in (stream_url or '').lower() or 'video-hls' in (stream_url or '').lower()
                
                # Force #hls.m3u8 if it is HLS to ensure frontend detection
                if is_hls and '.m3u8' not in (stream_url or '').lower():
                    if '#' in stream_url:
                        stream_url += '&hls.m3u8'
                    else:
                        stream_url += '#hls.m3u8'

                return {
                    "id": info.get('id'),
                    "title": info.get('title') or "VK Video",
                    "description": info.get('description') or "",
                    "thumbnail": info.get('thumbnail'),
                    "duration": info.get('duration') or 0,
                    "stream_url": stream_url,  # Use extracted stream URL
                    "width": best_format.get('width', 0) if best_format else 0,
                    "height": max_height,
                    "tags": info.get('tags', []),
                    "uploader": info.get('uploader') or "",
                    "is_hls": is_hls,
                    "source": "vk"  # Mark as VK for special handling
                }
        except Exception as e:
            logging.error(f"VK extraction failed for {url}: {e}")
            return None


def _playback_subset(full: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stream_url": full["stream_url"],
        "is_hls": full.get("is_hls", False),
        "height": full.get("height") or 0,
        "duration": full.get("duration") or 0,
    }


def _cache_key(url: str) -> str:
    u = (url or "").strip()
    if "?" in u:
        u = u.split("?", 1)[0]
    return u


def extract_vk_playback_resilient(
    page_url: str, *, force_refresh: bool = False
) -> Optional[Dict[str, Any]]:
    """
    Čerstvý playback URL pre VK stránku: retry + krátky in-memory cache.
    force_refresh=True obíde cache (napr. po 403 alebo expirovanom linke).
    """
    key = _cache_key(page_url)
    now = time.monotonic()
    if not force_refresh:
        with _VK_CACHE_LOCK:
            hit = _VK_PLAYBACK_CACHE.get(key)
            if hit and hit[0] > now:
                return dict(hit[1])

    ext = VKExtractor()
    last_err: Optional[Exception] = None
    for attempt in range(1, VK_PLAYBACK_RETRIES + 1):
        try:
            full = ext._extract_ytdlp(page_url)
            if full and full.get("stream_url"):
                payload = _playback_subset(full)
                ttl = VK_PLAYBACK_CACHE_TTL
                with _VK_CACHE_LOCK:
                    _VK_PLAYBACK_CACHE[key] = (now + ttl, dict(payload))
                return payload
        except Exception as e:
            last_err = e
            logging.warning(f"VK playback attempt {attempt}/{VK_PLAYBACK_RETRIES} failed: {e}")
        if attempt < VK_PLAYBACK_RETRIES:
            time.sleep(VK_PLAYBACK_RETRY_DELAY * attempt)

    if last_err:
        logging.error(f"VK playback failed after retries for {page_url}: {last_err}")
    return None
