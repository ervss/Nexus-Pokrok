import logging
import re
import asyncio
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import httpx
from .base import VideoExtractor

class TurboExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Turbo"

    def can_handle(self, url: str) -> bool:
        return "turbo.cr" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extracts metadata and stream URL for a single video.
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://turbo.cr/'
        }

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Extract ID from script
                # const VIDEO_ID = "y1vp_LXO-1dKe";
                video_id = None
                id_match = re.search(r'const VIDEO_ID\s*=\s*["\']([^"\']+)["\'];', resp.text)
                if id_match:
                    video_id = id_match.group(1)
                
                if not video_id:
                    # Fallback ID from URL
                    # https://turbo.cr/v/y1vp_LXO-1dKe
                    url_match = re.search(r'/v/([^/?#]+)', url)
                    if url_match:
                        video_id = url_match.group(1)

                if not video_id:
                    return None

                # Title
                title = ""
                og_title = soup.find('meta', property='og:title')
                if og_title:
                    title = og_title.get('content', '')
                if not title:
                    title_tag = soup.find('title')
                    if title_tag:
                        title = title_tag.text.strip()
                
                # Thumbnail
                thumbnail = ""
                og_image = soup.find('meta', property='og:image')
                if og_image:
                    thumbnail = og_image.get('content', '')

                # Duration
                duration = 0
                # Could be in metadata or script
                # Check for meta name="duration" or similar if available
                # In the provided HTML it wasn't obvious, but let's try some common ones
                dur_tag = soup.find('meta', property='video:duration')
                if dur_tag:
                    try:
                        duration = int(float(dur_tag.get('content', 0)))
                    except: pass

                # Stream URL
                # Based on analysis: https://turbo.cr/{id}.mp4
                # Or look for VIDEO_DIRECT in script
                stream_url = None
                direct_match = re.search(r'const VIDEO_DIRECT\s*=\s*["\']([^"\']+)["\'];', resp.text)
                if direct_match:
                    direct_path = direct_match.group(1).lstrip('\\')
                    if direct_path.startswith('/'):
                        stream_url = f"https://turbo.cr{direct_path}"
                    else:
                        stream_url = f"https://turbo.cr/{direct_path}"
                
                if not stream_url:
                    stream_url = f"https://turbo.cr/{video_id}.mp4"

                return {
                    "id": video_id,
                    "title": title,
                    "description": "",
                    "thumbnail": thumbnail,
                    "duration": duration,
                    "stream_url": stream_url,
                    "width": 0,
                    "height": 0,
                    "tags": [],
                    "uploader": "",
                    "is_hls": False
                }

        except Exception as e:
            logging.error(f"Turbo extraction failed for {url}: {e}")
            return None

    async def extract_album(self, url: str) -> List[str]:
        """
        Extracts all video URLs from an album page.
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://turbo.cr/'
        }

        found_urls = []
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Find table rows with file data
                rows = soup.find_all('tr', class_='file-row')
                for row in rows:
                    video_id = row.get('data-id')
                    if video_id:
                        found_urls.append(f"https://turbo.cr/v/{video_id}")
                
                # Fallback: find any /v/ links
                if not found_urls:
                    links = soup.find_all('a', href=re.compile(r'/v/[^/?#]+'))
                    for link in links:
                        href = link['href']
                        if not href.startswith('http'):
                            href = f"https://turbo.cr{href}"
                        found_urls.append(href)

            return list(dict.fromkeys(found_urls))

        except Exception as e:
            logging.error(f"Turbo album extraction failed for {url}: {e}")
            return []
