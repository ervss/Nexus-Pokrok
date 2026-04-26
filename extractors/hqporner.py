"""
Simple HQPorner Extractor using requests (no Selenium)
"""

import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict, Optional, Any
import asyncio
import logging

logger = logging.getLogger(__name__)

class HQPornerExtractor:
    """Simple HQPorner extractor using requests"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        logger.info("HQPorner Extractor initialized (requests-based)")
    
    @property
    def name(self) -> str:
        return "HQPorner"
    
    def can_handle(self, url: str) -> bool:
        return "hqporner.com" in url
    
    def search(self, keywords: str, min_quality: str = "1080p", added_within: str = "any", page: int = 1) -> List[Dict[str, Any]]:
        """
        Search HQPorner with keywords and filters
        """
        logger.info(f"Searching HQPorner: keywords='{keywords}', quality={min_quality}, page={page}")
        
        try:
            # Build search URL
            search_url = f"https://hqporner.com/?q={keywords}&p={page}"
            
            # Add quality filter
            if min_quality and min_quality != "any":
                quality_map = {"720p": "720", "1080p": "1080", "2160p": "2160", "4k": "2160"}
                if min_quality.lower() in quality_map:
                    search_url += f"&quality={quality_map[min_quality.lower()]}"
            
            # Add date filter
            if added_within and added_within != "any":
                date_map = {"today": "today", "this_week": "week", "this_month": "month"}
                if added_within.lower() in date_map:
                    search_url += f"&added={date_map[added_within.lower()]}"
            
            logger.info(f"Fetching: {search_url}")
            
            # Fetch page
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find video containers (use attribute selector since class names can't start with numbers)
            containers = soup.select('div[class~="6u"] section.box.feature')
            if not containers:
                # Fallback selector
                containers = soup.find_all('section', class_='box')
            
            logger.info(f"Found {len(containers)} video containers")
            
            results = []
            for container in containers:
                try:
                    # Find all video links in container
                    links = container.find_all('a', href=re.compile(r'/hdporn/\d+'))
                    if not links:
                        continue
                    
                    # Find the link that has text (title)
                    title = ""
                    url = ""
                    for link in links:
                        link_text = link.get_text(strip=True)
                        link_title_attr = link.get('title')
                        if (link_text or link_title_attr) and not title:
                            title = link_text or link_title_attr
                        if not url:
                            url = link.get('href')
                    
                    # Find thumbnail and alternative title from alt tag
                    img = container.find('img')
                    thumbnail = ""
                    alt_title = ""
                    if img:
                        thumbnail = img.get('src') or img.get('data-src') or ""
                        alt_title = img.get('alt', '').strip()
                        if thumbnail and thumbnail.startswith('//'):
                            thumbnail = f"https:{thumbnail}"
                        elif thumbnail and not thumbnail.startswith('http'):
                            thumbnail = f"https://hqporner.com{thumbnail}"
                    
                    # Fallback title if still empty
                    if not title:
                        title = alt_title
                    if not title:
                        h3 = container.find('h3')
                        if h3: title = h3.get_text(strip=True)
                    
                    title = title or "Untitled HQPorner Video"
                    
                    if not url.startswith('http'):
                        url = f"https://hqporner.com{url}"
                    
                    # Extract duration
                    duration = 0
                    dur_elem = container.select_one('.icon.fa-clock-o') or container.find(class_=re.compile(r'duration|time'))
                    if dur_elem:
                        dur_text = dur_elem.get_text(strip=True)
                        d_parts = re.findall(r'(\d+)([hms])', dur_text)
                        if d_parts:
                            for val, unit in d_parts:
                                if unit == 'h': duration += int(val) * 3600
                                elif unit == 'm': duration += int(val) * 60
                                elif unit == 's': duration += int(val)
                        elif ':' in dur_text:
                            parts = dur_text.split(':')
                            if len(parts) == 2: duration = int(parts[0])*60 + int(parts[1])
                            elif len(parts) == 3: duration = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
                    
                    # Extract quality from text
                    text = container.get_text()
                    width, height = 1920, 1080
                    if '4K' in text or '2160' in text:
                        width, height = 3840, 2160
                    elif '1080' in text:
                        width, height = 1920, 1080
                    elif '720' in text:
                        width, height = 1280, 720
                    
                    # Return basic info from search results
                    results.append({
                        "title": title,
                        "url": url,
                        "thumbnail": thumbnail,
                        "duration": duration,
                        "width": width,
                        "height": height
                    })
                    
                except Exception as e:
                    logger.debug(f"Error parsing container: {e}")
                    continue
            
            logger.info(f"Successfully extracted {len(results)} videos")
            return results
            
        except Exception as e:
            logger.error(f"Error during HQPorner search: {e}")
            return []
    
    async def extract(self, video_url: str) -> dict:
        """Extract full metadata and stream URL for a video (Async wrapper)"""
        return await asyncio.to_thread(self._get_video_meta, video_url)

    def _get_video_meta(self, video_url: str) -> dict:
        """Extract full metadata and stream URL for a video (Sync)"""
        stream_url = self._get_stream_url(video_url)
        if not stream_url:
            return {}
        
        # We could extract more here (tags, actress, etc) if needed
        return {
            "stream_url": stream_url
        }

    def _get_stream_url(self, video_url: str) -> str:
        """Extract stream URL from video page"""
        try:
            headers = {
                'Referer': 'https://hqporner.com/',
                'User-Agent': self.session.headers.get('User-Agent')
            }
            response = self.session.get(video_url, timeout=10, headers=headers)
            if response.status_code != 200:
                logger.debug(f"Video page returned {response.status_code}: {video_url}")
                return ""
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find iframe in known wrappers
            iframe = soup.select_one('#playerWrapper iframe, .videoWrapper iframe, .video-player iframe')
            if not iframe:
                # Try finding any iframe that points to a video hoster
                iframes = soup.find_all('iframe')
                for f in iframes:
                    src = f.get('src', '')
                    if any(x in src for x in ['mydaddy.cc', 'hqporner.com/player', 'external', 'embed']):
                        iframe = f
                        break
            
            if iframe:
                src = iframe.get('src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    
                    # If it's a mydaddy.cc player page, extract the actual video URL
                    if 'mydaddy.cc' in src:
                        actual_url = self._extract_mydaddy_url(src)
                        if actual_url:
                            return actual_url
                        # If extraction fails, return the player URL as fallback
                        logger.warning(f"Failed to extract video from mydaddy.cc, using player URL as fallback")
                    
                    return src
            
            # Try to find video tag
            video = soup.find('video')
            if video:
                src = video.get('src')
                if not src:
                    source = video.find('source')
                    if source:
                        src = source.get('src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    return src
            
            # Fallback: check for scripts with player data
            scripts = soup.find_all('script')
            for script in scripts:
                content = script.get_text()
                if 'player' in content.lower() and ('src' in content or 'file' in content):
                    match = re.search(r'["\'](https?:[^\s"\']+\.mp4[^\s"\']*)["\']', content)
                    if match:
                        return match.group(1)
            
            return ""
            
        except Exception as e:
            logger.debug(f"Error extracting stream URL: {e}")
            return ""
    
    def _extract_mydaddy_url(self, player_url: str) -> str:
        """Extract actual video URL from mydaddy.cc player page"""
        try:
            logger.debug(f"Extracting video URL from mydaddy.cc: {player_url}")
            
            # Fetch the mydaddy.cc player page
            headers = {
                'Referer': 'https://hqporner.com/',
                'User-Agent': self.session.headers.get('User-Agent')
            }
            response = self.session.get(player_url, timeout=10, headers=headers)
            if response.status_code != 200:
                logger.warning(f"mydaddy.cc page returned {response.status_code}")
                return ""
            
            # Look for bigcdn.cc video URLs in the page
            # Pattern: //s44.bigcdn.cc/pubs/69681c847bc354.70882185/
            match = re.search(r'//([a-z0-9]+\.bigcdn\.cc/pubs/[a-z0-9.]+/)', response.text)
            if match:
                base_path = 'https://' + match.group(1)
                # Default to 1080p, fallback to 720p if not available
                video_url = base_path + '1080.mp4'
                logger.debug(f"Successfully extracted video URL: {video_url}")
                return video_url
            
            logger.warning(f"Could not find bigcdn.cc URL in mydaddy.cc page")
            return ""
            
        except Exception as e:
            logger.warning(f"Failed to extract mydaddy.cc URL: {e}")
            return ""
    
    def search_category(self, category: str, page: int = 1, min_quality: str = "1080p", added_within: str = "any", keywords: str = "") -> List[Dict[str, Any]]:
        """Search by category with optional keyword filter"""
        logger.info(f"Searching category: {category}, keywords: '{keywords}'")
        
        try:
            category_url = f"https://hqporner.com/category/{category}?page={page}"
            
            # Add keyword filter if provided
            if keywords:
                category_url += f"&q={keywords}"
            
            # Add date filter
            if added_within and added_within != "any":
                date_map = {"today": "today", "this_week": "week", "this_month": "month"}
                if added_within.lower() in date_map:
                    category_url += f"&added={date_map[added_within.lower()]}"
            
            response = self.session.get(category_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            containers = soup.select('div[class~="6u"] section.box.feature')
            if not containers:
                containers = soup.find_all('section', class_='box')
            
            results = []
            for container in containers:
                try:
                    link = container.find('a', href=re.compile(r'/hdporn/\d+'))
                    if not link:
                        continue
                    
                    url = link.get('href')
                    if not url.startswith('http'):
                        url = f"https://hqporner.com{url}"
                    
                    title = link.get('title') or link.get_text(strip=True)
                    
                    img = container.find('img')
                    thumbnail = ""
                    if img:
                        thumbnail = img.get('src') or img.get('data-src') or ""
                        if thumbnail and not thumbnail.startswith('http'):
                            thumbnail = f"https:{thumbnail}" if thumbnail.startswith('//') else f"https://hqporner.com{thumbnail}"
                    
                    duration = 0
                    dur_elem = container.find(class_=re.compile(r'duration|time'))
                    if dur_elem:
                        dur_text = dur_elem.get_text(strip=True)
                        d_parts = re.findall(r'(\d+)([hms])', dur_text)
                        for val, unit in d_parts:
                            if unit == 'h':
                                duration += int(val) * 3600
                            elif unit == 'm':
                                duration += int(val) * 60
                            elif unit == 's':
                                duration += int(val)
                    
                    text = container.get_text()
                    width, height = 1920, 1080
                    if '4K' in text or '2160' in text:
                        width, height = 3840, 2160
                    elif '1080' in text:
                        width, height = 1920, 1080
                    elif '720' in text:
                        width, height = 1280, 720
                    
                    
                    results.append({
                        "title": title,
                        "url": url,
                        "thumbnail": thumbnail,
                        "duration": duration,
                        "width": width,
                        "height": height
                    })
                    
                except Exception as e:
                    logger.debug(f"Error parsing container: {e}")
                    continue
            
            logger.info(f"Found {len(results)} results from category '{category}'")
            return results
            
        except Exception as e:
            logger.error(f"Error during category search: {e}")
            return []
