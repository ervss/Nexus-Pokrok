import re
import json
import logging
import requests
import yt_dlp
import os
from .base import VideoExtractor
from typing import Optional, Dict, Any

class EpornerExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Eporner"
    
    @property
    def domains(self):
        return ["eporner.com", "www.eporner.com"]
    
    def can_handle(self, url: str) -> bool:
        return any(domain in url for domain in self.domains)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # Clean URL
        search_url = url
        logging.info(f"Extracting metadata from {search_url}")

        # Try Manual Extraction FIRST (Much faster than yt-dlp)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.eporner.com/'
            }
            
            # 1. Fetch HTML (with timeout)
            resp = requests.get(search_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                html = resp.text
                stream_url = None
                width = 0
                height = 0
                
                # Check for qualities in descending order (Regex Strategy)
                for quality in ['4k', '2160p', '1440p', '1080p', '720p', '480p', '360p']:
                    # Look for: "1080p": "https://..." or 1080p: "..."
                    # Regex matches optional quotes around key, flexible whitespace, and captures URL
                    pattern = rf'(?:["\']?{quality}["\']?)\s*:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']'
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        stream_url = match.group(1).replace('\\/', '/')
                        # Set resolution based on quality
                        if '4k' in quality or '2160' in quality: height = 2160; width = 3840
                        elif '1440' in quality: height = 1440; width = 2560
                        elif '1080' in quality: height = 1080; width = 1920
                        elif '720' in quality: height = 720; width = 1280
                        elif '480' in quality: height = 480; width = 854
                        elif '360' in quality: height = 360; width = 640
                        break
                
                # 2. Strategy: Download Links (if Regex failed)
                if not stream_url:
                    # Extract all dload links: /dload/123456/1080p/
                    # Use flexible regex to catch various formats
                    dload_matches = re.findall(r'href=["\'](/dload/[\w\d]+/(?:[\w\d]+)/?)["\']', html)
                    target_dload = None
                    
                    # Prioritize qualities
                    for q in ['4k', '2160', '1440', '1080', '720', '480', '360']:
                        for path in dload_matches:
                            if q in path:
                                target_dload = path
                                # Set dimensions guess
                                if '2160' in q or '4k' in q: height = 2160; width = 3840
                                elif '1440' in q: height = 1440; width = 2560
                                elif '1080' in q: height = 1080; width = 1920
                                elif '720' in q: height = 720; width = 1280
                                elif '480' in q: height = 480; width = 854
                                elif '360' in q: height = 360; width = 640
                                break
                        if target_dload: break
                    
                    # Resolve logic
                    if target_dload:
                        full_dload = f"https://www.eporner.com{target_dload}"
                        try:
                            # Use HEAD to follow redirect without downloading body
                            res_head = requests.head(full_dload, headers=headers, allow_redirects=True, timeout=5)
                            if res_head.status_code == 200:
                                stream_url = res_head.url
                                logging.info(f"[EPORNER_FAST] Resolved download link: {stream_url}")
                        except Exception as e:
                            logging.warning(f"[EPORNER_FAST] Download link resolution failed: {e}")

                if stream_url:
                    # 3. Extract Metadata
                    title = "Eporner Video"
                    title_match = re.search(r'<title>(.*?)</title>', html)
                    if title_match:
                        title = title_match.group(1).replace(' - EPORNER', '').strip()
                    
                    thumb_url = None
                    thumb_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
                    if not thumb_match:
                        thumb_match = re.search(r'["\']poster["\']\s*:\s*["\'](https?://[^"\']+)["\']', html)
                    if thumb_match:
                        thumb_url = thumb_match.group(1)
                    
                    duration = 0
                    dur_match = re.search(r'<meta\s+property="og:duration"\s+content="(\d+)"', html)
                    if dur_match:
                        duration = int(dur_match.group(1))
                    
                    # Extract Views (e.g. <span id="videoviews">5,110</span>)
                    views = 0
                    views_match = re.search(r'id=["\']videoviews["\'][^>]*>\s*([\d,]+)\s*<', html)
                    if views_match:
                        try:
                            views = int(views_match.group(1).replace(',', ''))
                        except: pass
                    
                    # Extract Upload Date (e.g. May 2, 2025)
                    upload_date = None
                    # Search near the resolution/duration info or metadata block
                    date_match = re.search(r'(\w{3,9}\s+\d{1,2},\s+\d{4})', html)
                    if date_match:
                        upload_date = date_match.group(1)
                    
                    # Extract Tags (keywords)
                    tags = []
                    # Look for div with class "keyw" or similar
                    keywords_div_match = re.search(r'<div[^>]*class=["\'](?:keyw|keywords|tags)["\'][^>]*>(.*?)</div>', html, re.DOTALL)
                    if keywords_div_match:
                        tags_html = keywords_div_match.group(1)
                        # Extract text from <a> tags
                        tags = re.findall(r'<a[^>]*>(.*?)</a>', tags_html)
                        tags = [t.strip() for t in tags if t.strip()]

                    logging.info(f"[EPORNER_FAST] Successfully extracted: {title} ({height}p) | Date: {upload_date} | Views: {views}")
                    return {
                        "id": None,
                        "title": title,
                        "description": "",
                        "thumbnail": thumb_url,
                        "duration": duration,
                        "stream_url": stream_url,
                        "width": width,
                        "height": height,
                        "tags": tags,
                        "views": views,
                        "upload_date": upload_date,
                        "uploader": "",
                        "is_hls": False
                    }
        except Exception as e:
            logging.warning(f"[EPORNER_FAST] Manual extraction failed: {e}. Falling back to yt-dlp.")

        logging.info("[EPORNER_FAST] Fast extraction yielded no result. Starting yt-dlp (slow)...")

        # Fallback to yt-dlp
        try:
            ytdlp_opts = {
                'quiet': True, 'ignoreerrors': True, 'no_warnings': True,
                'format': 'bestvideo+bestaudio/best',
                'extract_flat': False,
                'socket_timeout': 10, # IMPORTANT: Prevent hanging
                'retries': 3
            }
            
            if os.path.exists("eporner.netscape.txt"):
                ytdlp_opts['cookiefile'] = "eporner.netscape.txt"
            elif os.path.exists("cookies.netscape.txt"):
                ytdlp_opts['cookiefile'] = "cookies.netscape.txt"
            
            with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise Exception("yt-dlp returned no stream URL")

                best_format = None
                best_height = 0
                for f in info.get('formats', []):
                    if not f.get('url') or not f.get('height'):
                        continue
                    h = f.get('height') or 0
                    if h > best_height:
                        best_format = f
                        best_height = h
                
                stream_url = best_format['url'] if best_format else info.get('url')
                width = best_format.get('width') if best_format else info.get('width')
                height = best_format.get('height') if best_format else info.get('height')
                
                # Try to get views/date from yt-dlp info if available
                views = info.get('view_count', 0)
                upload_date = info.get('upload_date') # usually YYYYMMDD
                if upload_date and len(upload_date) == 8:
                    # Format nicely if possible, or keep as is
                    try:
                        import datetime
                        dt = datetime.datetime.strptime(upload_date, "%Y%m%d")
                        upload_date = dt.strftime("%b %d, %Y")
                    except: pass
                
                tags = info.get('tags', [])

                logging.info(f"[EPORNER_SLOW] yt-dlp extracted: {info.get('title')} ({height}p)")
                return {
                    "id": None,
                    "title": info.get('title'),
                    "description": info.get('description'),
                    "thumbnail": info.get('thumbnail'),
                    "duration": info.get('duration'),
                    "stream_url": stream_url,
                    "width": width,
                    "height": height,
                    "tags": tags,
                    "views": views,
                    "upload_date": upload_date,
                    "uploader": info.get('uploader'),
                    "is_hls": False
                }
        except Exception as e:
            logging.error(f"Eporner extraction failed completely: {e}")
            return None
