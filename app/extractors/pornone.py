import requests
import re
import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any
from .base import VideoExtractor

logger = logging.getLogger(__name__)

class PornOneExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "PornOne"

    def can_handle(self, url: str) -> bool:
        return "pornone.com" in url

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.pornone.com/"
        })
        # Handle age verification cookie if needed
        self.session.cookies.set("verified", "1", domain="pornone.com")
        self.session.cookies.set("age_verified", "1", domain="pornone.com")

    def search(self, keyword: str, count: int = 20) -> List[Dict[str, Any]]:
        """
        Search PornOne for keywords and return list of candidate results.
        """
        search_url = f"https://www.pornone.com/search/{keyword}/"
        try:
            resp = self.session.get(search_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Selector from browser subagent: a.videocard.linkage
            cards = soup.select('a.videocard.linkage')
            results = []
            
            for card in cards[:count]:
                try:
                    title_el = card.select_one('.videotitle')
                    title = title_el.get_text(strip=True) if title_el else "Unknown PornOne Video"
                    
                    page_url = card.get('href')
                    if page_url and not page_url.startswith('http'):
                        page_url = f"https://www.pornone.com{page_url}"
                    
                    thumb_el = card.select_one('img.thumbimg')
                    thumbnail = thumb_el.get('data-src') or thumb_el.get('src') if thumb_el else ""
                    
                    dur_el = card.select_one('.durlabel')
                    duration_str = dur_el.get_text(strip=True) if dur_el else "0:00"
                    
                    # Convert duration string (MM:SS or HH:MM:SS) to seconds
                    duration = 0
                    parts = duration_str.split(':')
                    if len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    
                    results.append({
                        "title": title,
                        "page_url": page_url,
                        "thumbnail": thumbnail,
                        "duration": duration,
                        "tags": [] # Tags are usually on the detail page
                    })
                except Exception as e:
                    logger.error(f"Error parsing PornOne search card: {e}")
            
            return results
        except Exception as e:
            logger.error(f"PornOne Search Error: {e}")
            return []

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract direct video source and metadata from a PornOne detail page.
        """
        try:
            # Note: This is a synchronous request in an async method. 
            # In production, use aiohttp or run_in_executor.
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')
            
            # 1. Extract Title
            title_el = soup.select_one('.videotitle')
            title = title_el.get_text(strip=True) if title_el else "PornOne Video"
            
            # 2. Extract Tags
            # Pattern from subagent: links containing /tags/ or similar
            tags = [a.get_text(strip=True) for a in soup.select('a[href*="/tags/"], a[href*="/category/"]')]
            
            # 3. Extract Duration
            duration = 0
            # Try to find it in meta tags or script
            dur_match = re.search(r'["\']duration["\']\s*:\s*["\']?(\d+)["\']?', html)
            if dur_match:
                duration = int(dur_match.group(1))
            else:
                dur_text_el = soup.select_one('.durlabel')
                if dur_text_el:
                    duration_str = dur_text_el.get_text(strip=True)
                    parts = duration_str.split(':')
                    if len(parts) == 2: duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3: duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

            # 4. Extract Stream URL
            # PornOne uses Video.js and often embeds MP4 links in the HTML
            # We look for .mp4 links in the whole HTML or inside <source> tags
            stream_url = None
            
            # Try <source> tags first
            sources = soup.select('video source')
            # Sort by resolution if possible (look for 1080, 720 in src)
            sources_list = []
            for s in sources:
                src = s.get('src')
                if src:
                    res = 0
                    if '1080' in src: res = 1080
                    elif '720' in src: res = 720
                    elif '480' in src: res = 480
                    sources_list.append((res, src))
            
            if sources_list:
                sources_list.sort(key=lambda x: x[0], reverse=True)
                stream_url = sources_list[0][1]
            
            if not stream_url:
                # Fallback: Deep Regex scan for .mp4 or .m3u8
                # Pattern found by subagent: https://s{node}.pornone.com/vid2/...
                mp4_matches = re.findall(r'["\'](https?://[^"\']+?\.mp4[^"\']*?)["\']', html)
                if mp4_matches:
                    # Prefer 1080p in filename
                    stream_url = next((m for m in mp4_matches if '1080' in m), mp4_matches[0])

            if not stream_url:
                m3u8_matches = re.findall(r'["\'](https?://[^"\']+?\.m3u8[^"\']*?)["\']', html)
                if m3u8_matches:
                    stream_url = m3u8_matches[0]

            if not stream_url:
                return None

            return {
                "id": url.split('/')[-2] if '/' in url else None,
                "title": title,
                "description": "",
                "thumbnail": soup.select_one('meta[property="og:image"]')['content'] if soup.select_one('meta[property="og:image"]') else "",
                "duration": duration,
                "stream_url": stream_url,
                "width": 1920 if '1080' in stream_url else (1280 if '720' in stream_url else 0),
                "height": 1080 if '1080' in stream_url else (720 if '720' in stream_url else 0),
                "tags": tags,
                "uploader": "",
                "is_hls": ".m3u8" in stream_url
            }
        except Exception as e:
            logger.error(f"PornOne Extraction Error for {url}: {e}")
            return None
