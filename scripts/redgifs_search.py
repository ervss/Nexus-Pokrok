import requests
import time
import logging
import sys
import os
import json
import subprocess
import tempfile
from typing import List, Dict, Optional, Tuple

# Configuration
REDGIFS_API_BASE = "https://api.redgifs.com/v2"
DASHBOARD_URL = "http://localhost:8001/api/download/external"
KEYWORDS = ["deepthroat", "bimbo", "pov", "4k", "fake tits", "vertical", "sloppy", "facial"]
RESULTS_PER_KEYWORD = 50
MAX_RETRIES = 3
TIMEOUT = 30 # Increased for downloading large files

# Quality Filters
MIN_DURATION = 30  # Seconds
MIN_RESOLUTION = 1080
ONLY_VERTICAL = False 
HD_ONLY = True
REJECTED_KEYWORDS = ["meme", "edit", "compilation", "remix", "gif", "loop"]
# We will use search keywords directly

# Tool Paths
FFPROBE_PATH = os.path.join(os.getcwd(), "ffprobe.exe")
if not os.path.exists(FFPROBE_PATH):
    FFPROBE_PATH = "ffprobe" # Fallback to system path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class RedGifsBrutalScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.redgifs.com/"
        })
        self.token = self._get_temporary_token()

    def _get_temporary_token(self) -> Optional[str]:
        """Fetch temporary bearer token from RedGIFs."""
        try:
            response = self.session.get(f"{REDGIFS_API_BASE}/auth/temporary", timeout=15)
            response.raise_for_status()
            token = response.json().get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
                return token
        except Exception as e:
            logger.error(f"Failed to fetch temporary token: {e}")
        return None

    def _request_with_retry(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Execute request with retry logic and backoff."""
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
                if response.status_code == 429:
                    wait = (attempt + 1) * 5
                    logger.warning(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                logger.error(f"Request failed (attempt {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
        return None

    def get_video_metadata(self, file_path: str) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """Extract duration, width, and height using ffprobe."""
        try:
            cmd = [
                FFPROBE_PATH,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-of", "json",
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                return None, None, None
            
            data = json.loads(result.stdout)
            stream = data["streams"][0]
            duration = float(stream.get("duration", 0))
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            return duration, width, height
        except Exception as e:
            logger.debug(f"FFprobe error: {e}")
            return None, None, None

    def is_video_high_quality(self, video_data: Dict) -> bool:
        """Check if video meets brutal-tier quality standards."""
        title = video_data.get("title", "").lower()
        tags = [t.lower() for t in video_data.get("tags", [])]
        
        # 1. Reject by text (using word boundaries to avoid false positives like 'redgifs' matching 'gif')
        full_text = title + " " + " ".join(tags)
        full_text = title.lower() + " " + " ".join(tags)
        import re
        for bad in REJECTED_KEYWORDS:
            if re.search(rf"\b{re.escape(bad)}\b", full_text, re.IGNORECASE):
                logger.info(f"⛔ Skipped: Match rejected keyword '{bad}' in '{title}'")
                return False
            
        # Keyword filter (using word boundaries)
        title_lower = title.lower()
        for bad in REJECTED_KEYWORDS:
            if re.search(rf"\b{re.escape(bad)}\b", title_lower, re.IGNORECASE):
                logger.info(f"❌ Skipped: rejected keyword '{bad}' in title - '{title}'")
                return False

        # 3. Download and check media properties
        video_url = video_data.get("video_url")
        if not video_url:
            return False

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
            try:
                # Stream download for efficiency
                with self.session.get(video_url, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        tmp.write(chunk)
                tmp.close()

                duration, width, height = self.get_video_metadata(tmp_path)

                if duration is None:
                    logger.warning(f"⚠️ Warning: Could not extract duration for '{title}'")
                    return False

                # Check Duration
                if duration < MIN_DURATION:
                    logger.info(f"⛔ Skipped: too short ({duration:.1f}s, min {MIN_DURATION}s) - '{title}'")
                    return False
                
                # Check Resolution
                if not width or not height:
                    logger.warning(f"⚠️ Warning: Could not extract resolution for '{title}'")
                    return False

                max_dim = max(width, height)
                if max_dim < MIN_RESOLUTION:
                    logger.info(f"⛔ Skipped: resolution {width}x{height} (Min {MIN_RESOLUTION}p) - '{title}'")
                    return False
                
                # Optional: Vertical only
                if ONLY_VERTICAL and height <= width:
                    logger.info(f"⛔ Skipped: not vertical ({width}x{height}) - '{title}'")
                    return False
                
                logger.info(f"✅ Verified Content: {width}x{height}, {duration:.1f}s - '{title}'")
                return True

            except Exception as e:
                logger.error(f"Error checking video quality: {e}")
                return False
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except: pass

    def search_videos(self, keyword: str, count: int = 50) -> List[Dict]:
        """Search for videos by keyword and return flattened results."""
        if not self.token:
            self.token = self._get_temporary_token()
            if not self.token: return []

        params = {
            "search_text": keyword,
            "count": count
        }
        
        response = self._request_with_retry("GET", f"{REDGIFS_API_BASE}/gifs/search", params=params)
        if not response:
            return []

        data = response.json()
        raw_gifs = data.get("gifs", [])
        logger.info(f"📊 Received {len(raw_gifs)} results from RedGIFs API for '{keyword}'")
        
        results = []
        for gif in raw_gifs:
            video_id = gif.get("id")
            urls = gif.get("urls", {})
            results.append({
                "title": gif.get("caption") or f"RedGIFs Video {video_id}",
                "tags": gif.get("tags", []),
                "video_url": urls.get("hd") or urls.get("sd"),
                "thumbnail_url": urls.get("thumbnail") or urls.get("poster"),
                "page_url": f"https://www.redgifs.com/watch/{video_id}"
            })
        return results

    def send_to_dashboard(self, video_data: Dict) -> bool:
        """Send verified video metadata to the dashboard."""
        payload = {
            "url": video_data["video_url"],
            "title": video_data["title"]
        }
        
        try:
            resp = requests.post(DASHBOARD_URL, json=payload, timeout=15)
            if resp.status_code in [200, 201]:
                logger.info(f"🚀 Successfully sent to dashboard: {video_data['title']}")
                logger.debug(f"Dashboard response: {resp.text}")
                return True
            else:
                logger.error(f"Failed to send to dashboard: Status {resp.status_code}, Body: {resp.text}")
        except Exception as e:
            logger.error(f"Error sending to dashboard: {e}")
        return False

def main():
    scraper = RedGifsBrutalScraper()
    
    for kw in KEYWORDS:
        logger.info(f"🔥 Starting search for '{kw}'...")
        videos = scraper.search_videos(kw, count=RESULTS_PER_KEYWORD)
        
        for video in videos:
            if video.get("video_url"):
                # Brutal filtering logic
                if scraper.is_video_high_quality(video):
                    scraper.send_to_dashboard(video)
                    time.sleep(1) # Extra throttle for verified imports
            
            # Throttle between results
            time.sleep(0.5)
        
        # Throttling between keywords
        time.sleep(3)

if __name__ == "__main__":
    main()
