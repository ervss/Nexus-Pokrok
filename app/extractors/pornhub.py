import logging
import asyncio
import yt_dlp
from typing import Optional, Dict, Any
from .base import VideoExtractor

logger = logging.getLogger(__name__)

class PornhubExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Pornhub"

    def can_handle(self, url: str) -> bool:
        return "pornhub.com" in url.lower()

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extracts metadata and stream URL from Pornhub using yt-dlp.
        """
        def _extract():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'format': 'best[protocol*=m3u8]/best[ext=mp4]/bestvideo+bestaudio/best',
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                if not info:
                    return None
                    
                stream_url = info.get('url')
                if not stream_url and info.get('formats'):
                    fmts = [f for f in info.get('formats', []) if f.get('url')]
                    if fmts:
                        # Prefer mp4 or m3u8 formats that are single file
                        fmts.sort(key=lambda f: (f.get('height') or 0), reverse=True)
                        stream_url = fmts[0]['url']
                        
                height = int(info.get('height') or 0)
                
                return {
                    "id": info.get('id', ''),
                    "title": info.get('title', ''),
                    "description": info.get('description', ''),
                    "thumbnail": info.get('thumbnail'),
                    "duration": float(info.get('duration') or 0.0),
                    "stream_url": stream_url,
                    "width": int(info.get('width') or 0),
                    "height": height,
                    "size_bytes": info.get('filesize') or info.get('filesize_approx'),
                    "tags": info.get('tags', []),
                    "uploader": info.get('uploader', ''),
                    "is_hls": bool(stream_url and '.m3u8' in stream_url)
                }
            except Exception as e:
                logger.error(f"Pornhub yt-dlp extraction failed for {url}: {e}")
                return None

        # Run yt-dlp extraction in a separate thread so we don't block the async loop
        return await asyncio.to_thread(_extract)
