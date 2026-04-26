
import requests
import re
from bs4 import BeautifulSoup
import logging

class TnaflixExtractor:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def can_handle(self, url: str) -> bool:
        return "tnaflix.com" in url

    def extract(self, url: str) -> dict:
        """
        Extracts metadata for a single video.
        """
        # Handle direct MP4 links from CDN
        if ".mp4" in url.lower():
            # Try to extract a clean title from the filename
            filename = url.split('/')[-1].split('?')[0]
            title = filename.replace('.mp4', '').replace('-', ' ').replace('_', ' ').title()
            
            # Simple metadata for direct links
            return {
                "title": title,
                "duration": 0,
                "thumbnail": None, # Direct link doesn't have a thumb easily available
                "stream_url": url,
                "tags": ""
            }

        try:
            resp = requests.get(url, headers=self.headers, timeout=15)
            if resp.status_code != 200:
                logging.error(f"Tnaflix: Failed to fetch {url}, status {resp.status_code}")
                return None
            
            # Check content type - if it's video, skip BeautifulSoup
            content_type = resp.headers.get('Content-Type', '')
            if 'video' in content_type:
                 filename = url.split('/')[-1].split('?')[0]
                 return {
                    "title": filename.replace('.mp4', '').title(),
                    "duration": 0,
                    "thumbnail": None,
                    "stream_url": url,
                    "tags": ""
                }

            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Title
            title_tag = soup.find("meta", property="og:title")
            title = title_tag["content"] if title_tag else "Unknown Tnaflix Video"
            
            # Thumbnail
            thumb_tag = soup.find("meta", property="og:image")
            thumbnail = thumb_tag["content"] if thumb_tag else None
            
            # Stream URL
            stream_url = None
            video_tag = soup.find("video")
            if video_tag:
                 sources = video_tag.find_all("source", src=True)
                 best_size = 0
                 for s in sources:
                     try:
                         size_attr = s.get("size", "0")
                         # Tnaflix uses size="4" for 4K/2160p videos
                         if size_attr == "4":
                             size = 2160
                         else:
                             size = int(size_attr)
                         
                         if size >= best_size:
                             best_size = size
                             stream_url = s["src"]
                     except:
                         if not stream_url:
                             stream_url = s["src"]
            
            if not stream_url:
                og_vid = soup.find("meta", property="og:video")
                if og_vid and ".mp4" in og_vid["content"]:
                    stream_url = og_vid["content"]

            # Duration
            duration = 0
            dur_el = soup.select_one(".duration, .video-time, .time")
            if dur_el:
                dur_text = dur_el.get_text(strip=True)
                try:
                    parts = dur_text.split(':')
                    if len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                    elif len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                except: pass

            # Tags
            tags = []
            tag_els = soup.select(".tags a, .video-info .tag a, .tag-container a")
            for t in tag_els:
                tags.append(t.get_text(strip=True))

            if stream_url and stream_url.startswith("//"):
                stream_url = "https:" + stream_url

            return {
                "title": title,
                "duration": duration,
                "thumbnail": thumbnail,
                "stream_url": stream_url or url,
                "tags": ",".join(tags)
            }

        except Exception as e:
            logging.error(f"Tnaflix extraction error: {e}")
            return None

    def extract_from_profile(self, url: str, max_results=200) -> list:
        """
        Crawls a profile page and extracts videos.
        Supports automatic pagination up to max_results.
        """
        results = []
        seen_urls = set()
        count = 0
        
        # Base URL for pagination (remove query params)
        base_url = url.split('?')[0]
        
        # Iterate pages (safety limit 20 pages)
        for page in range(1, 21):
            if count >= max_results: break
            
            # Construct page URL
            # Tnaflix pagination: ?page=2
            current_url = base_url if page == 1 else f"{base_url}?page={page}"
            if page > 1: logging.info(f"Scanning Tnaflix Profile Page {page}: {current_url}")
            
            try:
                 resp = requests.get(current_url, headers=self.headers, timeout=15)
                 if resp.status_code != 200:
                     logging.warning(f"Failed page {page}, status {resp.status_code}")
                     break
                 
                 soup = BeautifulSoup(resp.text, 'html.parser')
                 
                 # Links
                 links = soup.find_all('a', href=re.compile(r'/video\d+'))
                 if not links and page > 1:
                     # Stop if no videos found on subsequent pages
                     break
                 
                 # If we found links but all of them are already seen, we reached end/loop
                 new_links_on_page = 0
                 
                 for l in links:
                     if count >= max_results: break
                     
                     href = l['href']
                     if not href.startswith('http'):
                         href = "https://www.tnaflix.com" + href
                     
                     if href in seen_urls: continue
                     
                     seen_urls.add(href)
                     new_links_on_page += 1
                     
                     # Extract individual video
                     # Optimization: For profile mass import, we avoid full page load if possible?
                     # No, we need stream URL. But we can catch errors and continue.
                     try:
                        meta = self.extract(href)
                        if meta and meta.get('stream_url'):
                            results.append(meta)
                            count += 1
                     except Exception as ve:
                        logging.error(f"Failed to extract video {href}: {ve}")
                 
                 if new_links_on_page == 0:
                     logging.info(f"No new videos found on page {page}, stopping pagination.")
                     break
                     
            except Exception as e:
                logging.error(f"Tnaflix profile extraction error on page {page}: {e}")
                break
            
        return results
