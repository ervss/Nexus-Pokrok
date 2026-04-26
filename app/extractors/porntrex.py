"""
Porntrex Video Extractor
Handles video metadata extraction from Porntrex URLs.
"""
import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PorntrexExtractor:
    """Extractor for Porntrex videos."""

    @property
    def name(self) -> str:
        return "Porntrex"

    @property
    def domains(self):
        return ["porntrex.com", "www.porntrex.com"]

    def can_handle(self, url: str) -> bool:
        """Check if this extractor can handle the given URL."""
        return any(domain in url for domain in self.domains)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract video metadata and direct stream URL from Porntrex.
        OPTIMIZED: Fast regex-based extraction, similar to Eporner.

        Args:
            url: Porntrex video URL

        Returns:
            Dictionary with video metadata or None if extraction fails
        """
        try:
            logger.info(f"[PORNTREX_FAST] Extracting metadata from {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.porntrex.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }

            # Fetch page with timeout for speed
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.error(f"[PORNTREX_FAST] HTTP {resp.status_code} for {url}")
                return None

            html = resp.text

            # FAST PATH: Extract metadata using REGEX FIRST (avoid BeautifulSoup overhead)

            # Extract title - FAST regex first
            title = "Porntrex Video"
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).replace(' - PORNTREX', '').replace(' - Porntrex', '').strip()
            else:
                # Fallback: og:title meta tag
                title_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if title_match:
                    title = title_match.group(1).strip()

            # Extract thumbnail - FAST regex
            thumbnail = None
            thumb_match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if thumb_match:
                thumbnail = thumb_match.group(1)
            else:
                # Fallback: poster attribute
                poster_match = re.search(r'poster=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if poster_match:
                    thumbnail = poster_match.group(1)

            # Extract duration - FAST regex
            duration = 0
            duration_match = re.search(r'<meta\s+property=["\']video:duration["\']\s+content=["\'](\d+)["\']', html, re.IGNORECASE)
            if duration_match:
                try:
                    duration = int(duration_match.group(1))
                except:
                    pass

            if duration == 0:
                # Alternative duration pattern
                duration_match = re.search(r'duration["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE)
                if duration_match:
                    try:
                        duration = int(duration_match.group(1))
                    except:
                        pass

            # Only create BeautifulSoup if we need it for video tag fallback
            soup = None

            # FAST PATH: Extract video sources using REGEX FIRST (like Eporner)
            stream_url = None
            width = 0
            height = 0

            # Strategy 1: FAST - Regex search for quality URLs in HTML (PRIORITY)
            # This is 10x faster than BeautifulSoup parsing
            for quality in ['2160p', '1440p', '1080p', '720p', '480p', '360p']:
                # Match patterns like: "1080p":"https://..." or '1080p': "..."
                pattern = rf'["\']?{quality}["\']?\s*:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']'
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    stream_url = match.group(1).replace('\\/', '/')
                    height = int(quality.replace('p', ''))
                    width = int(height * 16 / 9)
                    logger.info(f"[PORNTREX_FAST] Found {quality} URL via regex")
                    break

            # Strategy 2: FAST - Find any MP4 URL in HTML
            if not stream_url:
                mp4_matches = re.findall(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html)
                if mp4_matches:
                    # Take the first match, try to guess quality from URL
                    for mp4_url in mp4_matches:
                        if '2160' in mp4_url or '4k' in mp4_url.lower():
                            stream_url = mp4_url
                            height = 2160
                            width = 3840
                            break
                        elif '1440' in mp4_url:
                            stream_url = mp4_url
                            height = 1440
                            width = 2560
                            break
                        elif '1080' in mp4_url:
                            stream_url = mp4_url
                            height = 1080
                            width = 1920
                            break
                        elif '720' in mp4_url:
                            stream_url = mp4_url
                            height = 720
                            width = 1280
                            break

                    # If no quality found in URL, use first match
                    if not stream_url and mp4_matches:
                        stream_url = mp4_matches[0]
                        height = 720  # Default assumption
                        width = 1280

                    if stream_url:
                        logger.info(f"[PORNTREX_FAST] Found MP4 URL via regex: {height}p")

            # Strategy 3: SLOW FALLBACK - Parse video tag sources (only if regex failed)
            if not stream_url:
                logger.info(f"[PORNTREX_FAST] Regex extraction failed, trying video tag parsing...")
                # Only create BeautifulSoup now if we really need it
                if soup is None:
                    soup = BeautifulSoup(html, 'html.parser')

                video_tag = soup.find('video')
                if video_tag:
                    source_tags = video_tag.find_all('source')
                    best_source = None
                    best_height = 0

                    for source in source_tags:
                        src = source.get('src')
                        label = source.get('label', '').lower()
                        res = source.get('res', '').lower()

                        if src:
                            # Determine quality
                            h = 0
                            if '2160' in label or '4k' in label or '2160' in res:
                                h = 2160
                            elif '1440' in label or '1440' in res:
                                h = 1440
                            elif '1080' in label or '1080' in res:
                                h = 1080
                            elif '720' in label or '720' in res:
                                h = 720
                            elif '480' in label or '480' in res:
                                h = 480

                            if h > best_height:
                                best_height = h
                                best_source = src

                    if best_source:
                        stream_url = best_source
                        height = best_height if best_height > 0 else 1080
                        width = int(height * 16 / 9)
                        logger.info(f"[PORNTREX_FAST] Found URL via video tag: {height}p")

            if not stream_url:
                logger.error(f"[PORNTREX] No stream URL found for {url}")
                return None

            # Extract views - FAST regex
            views = 0
            views_match = re.search(r'(\d+(?:,\d+)*)\s*views?', html, re.IGNORECASE)
            if views_match:
                try:
                    views = int(views_match.group(1).replace(',', ''))
                except:
                    pass

            # Extract tags - FAST regex (find all <a> tags in tags section)
            tags = []
            tags_matches = re.findall(r'(?:class=["\'](?:tag|category)[^>]*>|/tags?/[^"\'<>]+["\'])[^>]*>([^<]+)</a>', html, re.IGNORECASE)
            if tags_matches:
                tags = [tag.strip() for tag in tags_matches if tag.strip()]

            # Extract uploader - FAST regex
            uploader = ""
            uploader_match = re.search(r'(?:uploader|author|user)[^>]*>([^<]+)</a>', html, re.IGNORECASE)
            if uploader_match:
                uploader = uploader_match.group(1).strip()

            logger.info(f"[PORNTREX_FAST] Successfully extracted: {title} ({height}p) in ~{int((resp.elapsed.total_seconds())*1000)}ms")

            return {
                "id": None,
                "title": title,
                "description": "",
                "thumbnail": thumbnail,
                "duration": duration,
                "stream_url": stream_url,
                "width": width,
                "height": height,
                "tags": tags,
                "views": views,
                "upload_date": None,
                "uploader": uploader,
                "is_hls": False
            }

        except Exception as e:
            logger.error(f"[PORNTREX] Extraction failed for {url}: {e}", exc_info=True)
            return None
