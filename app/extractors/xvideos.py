import yt_dlp
import logging
import asyncio
import re
from .base import VideoExtractor
from typing import Optional, Dict, Any

class XVideosExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "XVideos"

    def can_handle(self, url: str) -> bool:
        return "xvideos.com" in url or "xvideos.red" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # Normalize URL (convert red to com if needed for certain extractors, or keep it)
        # Actually xvideos.red usually works directly or redirects.
        
        # 1. Try yt-dlp first (it's often faster)
        meta = self._extract_ytdlp(url)
        if meta and meta.get('height', 0) > 720:
             return meta
             
        # 2. If yt-dlp fails or returns low quality, try Playwright (Nuclear Option)
        try:
            from extractors.xvideos import XVideosExtractor as PWXVideos
            logging.info(f"Using Playwright Extractor for {url}")
            xv = PWXVideos()
            pw_res = await xv.extract_metadata(url)
            
            if pw_res and pw_res.get('found'):
                is_hls = 'hls' in (pw_res.get('quality_source') or '').lower() or '.m3u8' in pw_res['stream_url']
                return {
                    "id": meta.get('id') if meta else None, # preserve ID if we had it
                    "title": pw_res['title'],
                    "description": "",
                    "thumbnail": pw_res.get('thumbnail_url'),
                    "duration": meta.get('duration') if meta else 0,
                    "stream_url": pw_res['stream_url'],
                    "width": 1920 if is_hls else 0, # Assume HD
                    "height": 1080 if is_hls else 0,
                    "tags": meta.get('tags') if meta else [],
                    "uploader": "",
                    "is_hls": is_hls
                }
        except ImportError:
            pass # Playwright extractor not available
        except Exception as e:
            logging.error(f"Playwright fallback failed: {e}")

        return meta # Return whatever we got from yt-dlp (even if low quality)

    def _extract_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        import os
        email = os.getenv("XVIDEOS_EMAIL")
        password = os.getenv("XVIDEOS_PASSWORD")
        
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ydl_opts = {
            'quiet': True, 'skip_download': True, 'extract_flat': False,
            # Prefer highest resolution MP4, then HLS, then anything
            'format': 'bestvideo[ext=mp4][height>=2160]+bestaudio/bestvideo[ext=mp4][height>=1080]+bestaudio/bestvideo+bestaudio/best',
            'ignoreerrors': True, 'no_warnings': True,
            'user_agent': user_agent,
            'http_headers': {'User-Agent': user_agent, 'Referer': 'https://www.xvideos.com/'}
        }
        
        if email and password:
            ydl_opts['username'] = email
            ydl_opts['password'] = password
        
        # Cookie file search order: dedicated xvideos > general cookies
        for cookie_path in ["xvideos.netscape.txt", "xvideos.cookies.txt", "cookies.netscape.txt"]:
            if os.path.exists(cookie_path):
                ydl_opts['cookiefile'] = cookie_path
                break
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info: return None

                formats = info.get('formats', [])
                valid_formats = []
                for f in formats:
                    if not f.get('url'): continue
                    height = f.get('height') or 0
                    if height == 0:
                        note = (f.get('format_note') or '') + (f.get('format_id') or '')
                        match = re.search(r'(\d{3,4})p', note)
                        if match: height = int(match.group(1))
                    
                    is_hls = '.m3u8' in f.get('url', '') or 'hls' in f.get('protocol', '').lower()
                    is_mp4 = f.get('ext', '') == 'mp4' or '.mp4' in f.get('url', '')
                    
                    # For HLS without detected resolution, assume 1080 (conservative)
                    if is_hls and height == 0: height = 1080
                    
                    # Score: prefer MP4 at high res, then HLS
                    # Bonus for MP4 (easier to seek/stream), penalty for HLS unless high res
                    score = height * 10
                    if is_mp4 and not is_hls: score += 5  # small MP4 bonus
                    
                    valid_formats.append({
                        'url': f['url'],
                        'height': height,
                        'is_hls': is_hls,
                        'is_mp4': is_mp4,
                        'score': score,
                        'format_id': f.get('format_id', '')
                    })

                # Sort: highest score first
                valid_formats.sort(key=lambda x: x['score'], reverse=True)
                best = valid_formats[0] if valid_formats else {
                    'url': info.get('url'), 'height': 0, 'is_hls': False, 'is_mp4': False, 'score': 0
                }
                
                logging.info(f"[XVideos] Best format: {best.get('height')}p {'HLS' if best['is_hls'] else 'MP4'} for {url}")

                return {
                    "id": info.get('id'),
                    "title": info.get('title'),
                    "description": info.get('description'),
                    "thumbnail": info.get('thumbnail'),
                    "duration": info.get('duration'),
                    "stream_url": best['url'],
                    "width": 0,
                    "height": best['height'],
                    "tags": info.get('tags', []),
                    "uploader": info.get('uploader'),
                    "is_hls": best.get('is_hls', False)
                }
        except Exception as e:
            logging.warning(f"[XVideos] yt-dlp failed for {url}: {e}")
            return None

