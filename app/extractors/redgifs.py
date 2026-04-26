import requests
import time
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class RedGifsExtractor:
    API_BASE = "https://api.redgifs.com/v2"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.redgifs.com/"
        })
        self.token = self._get_temporary_token()

    def _get_temporary_token(self) -> Optional[str]:
        try:
            response = self.session.get(f"{self.API_BASE}/auth/temporary", timeout=15)
            response.raise_for_status()
            token = response.json().get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
                return token
        except Exception as e:
            logger.error(f"RedGIFs Token Error: {e}")
        return None

    def search(self, keyword: str, count: int = 20, hd_only: bool = False) -> List[Dict]:
        if not self.token:
            self.token = self._get_temporary_token()
            if not self.token: return []

        params = {
            "search_text": keyword,
            "count": count,
            "order": "recent"
        }
        
        try:
            resp = self.session.get(f"{self.API_BASE}/gifs/search", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            results = []
            for gif in data.get("gifs", []):
                urls = gif.get("urls", {})
                video_url = urls.get("hd") or urls.get("sd")
                
                if hd_only and not urls.get("hd"):
                    continue

                results.append({
                    "title": gif.get("caption") or f"RedGIFs {gif.get('id')}",
                    "video_url": video_url,
                    "thumbnail": urls.get("thumbnail") or urls.get("poster"),
                    "page_url": f"https://www.redgifs.com/watch/{gif.get('id')}",
                    "tags": gif.get("tags", [])
                })
            return results
        except Exception as e:
            logger.error(f"RedGIFs Search Error: {e}")
            return []
