import praw
import os
import json
import logging
import subprocess
import time
import requests
from typing import List, Dict, Optional, Tuple

from dotenv import load_dotenv

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Replace with your Reddit API credentials or use environment variables
CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
USER_AGENT = "AntigravityDashboard/1.0"

class RedditExtractor:
    def __init__(self):
        if CLIENT_ID == "YOUR_CLIENT_ID" or not CLIENT_ID:
            logger.warning("⚠️ Reddit credentials (CLIENT_ID/SECRET) not found in .env. Reddit ingestion will likely fail or be restricted.")
            self.reddit = None
        else:
            self.reddit = praw.Reddit(
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                user_agent=USER_AGENT
            )
        self.session = requests.Session()

    def get_video_info(self, url: str) -> Tuple[Optional[float], Optional[int], Optional[int], Optional[str]]:
        """Resolves Reddit URL to direct MP4 and extracts metadata via FFprobe."""
        try:
            # Get real MP4 via yt-dlp
            cmd_info = ["yt-dlp", "-g", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", url]
            res_info = subprocess.run(cmd_info, capture_output=True, text=True, timeout=30)
            if res_info.returncode != 0:
                return None, None, None, None
            
            real_url = res_info.stdout.strip().split('\n')[0]
            
            # Extract metadata
            ffprobe_path = "ffprobe" # Assumes standard path or in workspace
            cmd_probe = [
                ffprobe_path, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration", "-of", "json", real_url
            ]
            res_probe = subprocess.run(cmd_probe, capture_output=True, text=True, timeout=30)
            if res_probe.returncode != 0:
                return None, None, None, real_url
            
            data = json.loads(res_probe.stdout)
            stream = data["streams"][0]
            
            duration = float(stream.get("duration", 0))
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            
            return duration, width, height, real_url
        except Exception as e:
            logger.error(f"Reddit metadata extraction failed: {e}")
            return None, None, None, None

    def search_subreddit(self, sub_name: str, limit: int = 50) -> List[Dict]:
        """Scrapes hot posts from a subreddit, returning video candidates."""
        if not self.reddit:
            logger.error("Reddit PRAW not initialized. Check credentials.")
            return []
        try:
            subreddit = self.reddit.subreddit(sub_name)
            results = []
            for post in subreddit.hot(limit=limit):
                if not post.over_18: continue
                if not (post.is_video or "v.redd.it" in post.url): continue
                
                results.append({
                    "title": post.title,
                    "url": post.url,
                    "id": post.id,
                    "permalink": f"https://reddit.com{post.permalink}"
                })
            return results
        except Exception as e:
            logger.error(f"Subreddit {sub_name} search failed: {e}")
            return []
