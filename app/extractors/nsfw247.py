from .base import VideoExtractor
import httpx
from bs4 import BeautifulSoup
import re
import urllib.parse
from typing import Optional, Dict, Any
import logging

class NSFW247Extractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "NSFW247"

    def can_handle(self, url: str) -> bool:
        return "nsfw247.to" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, verify=False) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                # 1. Parse Title correctly (Clean)
                title = ""
                # Priority 1: OG Title
                og_title = soup.find('meta', property='og:title')
                if og_title and og_title.get('content'):
                    title = og_title['content']
                
                # Priority 2: H1
                if not title:
                    h1 = soup.find('h1')
                    if h1:
                        title = h1.get_text(strip=True)
                
                # Priority 3: Title tag
                if not title:
                    t_tag = soup.find('title')
                    if t_tag:
                        title = t_tag.get_text(strip=True)
                
                # Clean title (remove common site suffixes)
                if title:
                    title = title.split(' OnlyFans leak')[0]
                    title = title.split(' via NSFW247')[0]
                    title = title.split('| NSFW247')[0]
                    title = title.strip()

                # 2. Extract Video Stream
                stream_url = None
                # Look for video/source tags
                video_tag = soup.find('video')
                if video_tag:
                    if video_tag.get('src'):
                        stream_url = urllib.parse.urljoin(url, video_tag['src'])
                    else:
                        source_tag = video_tag.find('source')
                        if source_tag and source_tag.get('src'):
                            stream_url = urllib.parse.urljoin(url, source_tag['src'])
                
                # Fallback: regex search for common video formats if tags are empty/dynamic
                if not stream_url:
                    # Look for nsfwclips.co explicitly as it's common on this site
                    clips_match = re.search(r'https?://nsfwclips\.co/[^"\'\s>]+', resp.text)
                    if clips_match:
                        stream_url = clips_match.group(0)
                        # Fix encoding if needed (though browser/httpx usually handle it)
                        stream_url = stream_url.replace('&#038;', '&')

                # 3. Extract Thumbnail
                thumbnail = None
                og_image = soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    thumbnail = og_image['content']
                
                if not thumbnail and video_tag and video_tag.get('poster'):
                    thumbnail = urllib.parse.urljoin(url, video_tag['poster'])

                # 4. ID (from URL slug)
                video_id = url.split('/')[-1] or url.split('/')[-2]

                return {
                    "id": video_id,
                    "title": title or "NSFW247 Video",
                    "description": "",
                    "thumbnail": thumbnail,
                    "duration": 0, # To be determined by FFprobe later
                    "stream_url": stream_url,
                    "width": 0,
                    "height": 0,
                    "tags": [],
                    "uploader": "NSFW247",
                    "is_hls": stream_url.endswith('.m3u8') if stream_url else False
                }

        except Exception as e:
            logging.error(f"NSFW247 Extraction Error: {e}")
            return None
