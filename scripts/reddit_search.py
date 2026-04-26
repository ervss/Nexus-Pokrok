import praw
import os
import sys
import json
import logging
import subprocess
import time
import tempfile
import requests
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# === CONFIGURATION ===
# Replace with your Reddit API credentials
# Get them from https://www.reddit.com/prefs/apps
CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
USER_AGENT = "AntigravityDashboard/1.0 (by /u/YOUR_USERNAME)"

SUBREDDITS = ["DeepThroatLove", "Bimbofication", "NSFW_GIF", "Amateur"]
SEARCH_LIMIT = 50
DASHBOARD_URL = "http://localhost:8001/api/download/external"

# Quality Filters
MIN_DURATION = 30  # seconds
MIN_RESOLUTION = 1080 # height or width
ONLY_VERTICAL = False
HD_ONLY = True

# Reject keywords in title
REJECT_KEYWORDS = ["meme", "edit", "compilation", "remix", "gif", "loop"]

# Tool Paths
FFPROBE_PATH = os.path.join(os.getcwd(), "ffprobe.exe")
if not os.path.exists(FFPROBE_PATH):
    FFPROBE_PATH = "ffprobe"

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class RedditBrutalScraper:
    def __init__(self):
        if CLIENT_ID == "YOUR_CLIENT_ID" or not CLIENT_ID:
            logger.error("⚠️ Reddit credentials not found. Please set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env")
            self.reddit = None
        else:
            self.reddit = praw.Reddit(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                user_agent=USER_AGENT
            )
        self.session = requests.Session()

    def get_video_metadata(self, url: str) -> Tuple[Optional[float], Optional[int], Optional[int], Optional[str]]:
        """Use yt-dlp to find the true mp4 URL and FFprobe for quality check."""
        try:
            # Step 1: Get the real MP4 URL from Reddit/v.redd.it
            # We use yt-dlp because Reddit DASH manifests are tricky
            cmd_info = [
                "yt-dlp",
                "-g", # get url
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                url
            ]
            res_info = subprocess.run(cmd_info, capture_output=True, text=True)
            if res_info.returncode != 0:
                return None, None, None, None
            
            real_url = res_info.stdout.strip().split('\n')[0] # Usually first line is video
            
            # Step 2: Use ffprobe on the network URL (or download first part)
            # Fetching just the header via ffprobe is faster
            cmd_probe = [
                FFPROBE_PATH,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-of", "json",
                real_url
            ]
            res_probe = subprocess.run(cmd_probe, capture_output=True, text=True)
            if res_probe.returncode != 0:
                return None, None, None, real_url
            
            data = json.loads(res_probe.stdout)
            stream = data["streams"][0]
            
            duration = float(stream.get("duration", 0))
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            
            return duration, width, height, real_url
        except Exception as e:
            logger.debug(f"Metadata extraction error: {e}")
            return None, None, None, None

    def validate_quality(self, title: str, duration: float, width: int, height: int) -> bool:
        """Apply brutal tier filters."""
        # Keyword filter (using word boundaries)
        import re
        title_lower = title.lower()
        for bad in REJECT_KEYWORDS:
            if re.search(rf"\b{re.escape(bad)}\b", title_lower, re.IGNORECASE):
                logger.info(f"❌ Skipped: rejected keyword '{bad}' in title - '{title}'")
                return False

        if duration is None:
            logger.warning(f"⚠️ Warning: Could not extract duration for '{title}'")
            return False

        # Check Duration
        if duration < MIN_DURATION:
            logger.info(f"⛔ Skipped: too short ({duration:.1f}s, min {MIN_DURATION}s) - '{title}'")
            return False

        # Resolution filter
        max_dim = max(width, height)
        if max_dim < MIN_RESOLUTION:
            logger.info(f"❌ Skipped: resolution {width}x{height} < {MIN_RESOLUTION} (min {MIN_RESOLUTION}) - '{title}'")
            return False

        # Vertical filter
        if ONLY_VERTICAL and height <= width:
            logger.info(f"❌ Skipped: not vertical ({width}x{height}) - '{title}'")
            return False

        return True

    def send_to_dashboard(self, url: str, title: str):
        """Post to Antigravity Dashboard."""
        try:
            payload = {"url": url, "title": title}
            resp = self.session.post(DASHBOARD_URL, json=payload, timeout=15)
            if resp.status_code in [200, 201]:
                logger.info(f"✅ Imported: {title}")
                return True
            else:
                logger.error(f"Post failed (Status {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Dashboard connection error: {e}")
        return False

    def scrape(self):
        if not self.reddit:
            logger.error("⚠️ Reddit ingestion skipped: Missing credentials.")
            return

        for sub_name in SUBREDDITS:
            logger.info(f"🚀 Scraping r/{sub_name}...")
            try:
                subreddit = self.reddit.subreddit(sub_name)
                # 'hot' or 'new'
                for post in subreddit.hot(limit=SEARCH_LIMIT):
                    if not post.over_18:
                        continue
                        
                    # Target v.redd.it or direct video links
                    if not (post.is_video or "v.redd.it" in post.url):
                        continue

                    logger.info(f"🧐 Checking: {post.title[:50]}...")
                    
                    duration, width, height, real_url = self.get_video_metadata(post.url)
                    
                    if not real_url:
                        logger.warning(f"❌ Skipped: could not resolve .mp4 host - '{post.title[:50]}'")
                        continue

                    if self.validate_quality(post.title, duration or 0, width or 0, height or 0):
                        logger.info(f"💎 Quality Verified: {width}x{height} @ {duration:.1f}s")
                        self.send_to_dashboard(real_url, post.title)
                        time.sleep(1) # Throttling dashboard hits
                    
                    time.sleep(0.2) # Throttling Reddit processing

            except Exception as e:
                logger.error(f"Error scraping r/{sub_name}: {e}")
            
            time.sleep(2) # Cooldown between subreddits

if __name__ == "__main__":
    scraper = RedditBrutalScraper()
    scraper.scrape()
