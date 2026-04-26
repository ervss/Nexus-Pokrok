import logging
import re
import asyncio
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import httpx
from .base import VideoExtractor

class VidaraExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Vidara"

    def can_handle(self, url: str) -> bool:
        return "vidara.so" in url or "vidara.xyz" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extracts metadata and stream URL for a Vidara video using their API.
        """
        # Extract filecode from URL: https://vidara.so/e/XW9Na9PdjUrE -> XW9Na9PdjUrE
        filecode_match = re.search(r'/(?:e|v)/([^/?#]+)', url)
        if not filecode_match:
            logging.error(f"VidaraExtractor: Could not extract filecode from {url}")
            return None
        
        filecode = filecode_match.group(1)
        api_url = "https://vidara.so/api/stream"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Referer': f'https://vidara.so/e/{filecode}',
            'Content-Type': 'application/json',
            'Origin': 'https://vidara.so'
        }

        payload = {
            "filecode": filecode,
            "device": "web"
        }

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers, verify=False) as client:
                # 1. Fetch metadata and stream URL via API
                resp = await client.post(api_url, json=payload)
                if resp.status_code != 200:
                    logging.error(f"VidaraExtractor: API returned {resp.status_code} for {filecode}")
                    return None
                
                data = resp.json()
                stream_url = data.get("streaming_url")
                
                if not stream_url:
                    logging.warning(f"VidaraExtractor: API response missing streaming_url for {filecode}")
                    return None

                # 2. Extract title and thumbnail from API or page
                title = data.get("title") or "Vidara Video"
                thumbnail = data.get("thumbnail")
                duration = data.get("duration") or 0
                
                # If API metadata is poor, we could fallback to page scrape, 
                # but streaming_url is the most important part.

                # Height/Resolution guess from URL if possible
                height = 0
                if "1080" in stream_url: height = 1080
                elif "720" in stream_url: height = 720
                elif "480" in stream_url: height = 480

                return {
                    "id": filecode,
                    "title": title,
                    "description": "",
                    "thumbnail": thumbnail or "",
                    "duration": int(duration) if duration else 0,
                    "stream_url": stream_url,
                    "width": 0,
                    "height": height,
                    "tags": ["vidara"],
                    "uploader": "Vidara",
                    "is_hls": True
                }

        except Exception as e:
            logging.error(f"Vidara extraction failed for {url}: {e}")
            return None
