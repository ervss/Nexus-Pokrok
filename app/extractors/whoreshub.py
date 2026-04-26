"""
WhoresHub Video Extractor
Handles video metadata extraction from WhoresHub URLs including embedded players.
"""
import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class WhoresHubExtractor:
    """Extractor for WhoresHub videos."""

    @property
    def name(self) -> str:
        return "WhoresHub"

    @property
    def domains(self):
        return ["whoreshub.com", "www.whoreshub.com"]

    def can_handle(self, url: str) -> bool:
        """Check if this extractor can handle the given URL."""
        return any(domain in url for domain in self.domains)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract video metadata and direct stream URL from WhoresHub.
        OPTIMIZED: Fast regex-based extraction, similar to Porntrex.
        Handles both direct video URLs and embedded players (Streamtape, Dood, etc.)

        Args:
            url: WhoresHub video URL

        Returns:
            Dictionary with video metadata or None if extraction fails
        """
        try:
            logger.info(f"[WHORESHUB_FAST] Extracting metadata from {url}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://whoreshub.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            }

            # Fetch page with timeout for speed
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                logger.error(f"[WHORESHUB_FAST] HTTP {resp.status_code} for {url}")
                return None

            html = resp.text

            # FAST PATH: Extract metadata using REGEX FIRST (avoid BeautifulSoup overhead)

            # Extract title - FAST regex first
            title = "WhoresHub Video"
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).replace(' - WhoresHub', '').replace(' - WHORESHUB', '').strip()
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
            
            if thumbnail and thumbnail.startswith('//'):
                thumbnail = 'https:' + thumbnail

            # Extract duration - FAST regex
            duration = 0
            
            # Strategy 1: Check icon-duration pattern
            time_match = re.search(r'icon-duration.*?value[^>]*>\s*(\d+):(\d+)(?::(\d+))?\s*<', html, re.DOTALL | re.IGNORECASE)
            if time_match:
                try:
                    if time_match.group(3):  # HH:MM:SS
                        duration = int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + int(time_match.group(3))
                    else:  # MM:SS
                        duration = int(time_match.group(1)) * 60 + int(time_match.group(2))
                except:
                    pass

            if duration == 0:
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
                        
            # Extract size - Check for MB/GB
            size_bytes = None
            size_match = re.search(r'(?i)(?:MB|GB|KB)\s*<(?:/a|/span|/div)[^>]*>.*?(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>MB|GB|KB)', html)
            # Actually, the file size is right in the <a> tag: MP4 720p, 821.41 Mb
            size_match = re.search(r'(?i)(\d+(?:\.\d+)?)\s*(MB|GB|KB)', html)
            if size_match:
                try:
                    val = float(size_match.group(1))
                    unit = size_match.group(2).upper()
                    if unit == 'GB':
                        size_bytes = int(val * 1024 * 1024 * 1024)
                    elif unit == 'MB':
                        size_bytes = int(val * 1024 * 1024)
                    elif unit == 'KB':
                        size_bytes = int(val * 1024)
                except:
                    pass

            # Only create BeautifulSoup if we need it for fallback
            soup = None

            # FAST PATH: Extract video sources using REGEX FIRST (like Porntrex)
            stream_url = None
            width = 0
            height = 0
            is_hls = False

            # Strategy 1: FAST - Regex search for quality URLs in HTML (PRIORITY)
            # This is 10x faster than BeautifulSoup parsing
            for quality in ['2160p', '1440p', '1080p', '720p', '480p', '360p']:
                # Try multiple pattern variations to match different JS structures
                patterns = [
                    # Standard: "1080p":"https://..." or '1080p': "..."
                    rf'["\']?{quality}["\']?\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    # Numeric key: 1080: "url"
                    rf'{quality.replace("p", "")}\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    # file: "url", label: "1080p" format
                    rf'file\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']+)["\'][^}}]*label\s*:\s*["\']?{quality}',
                    # video_1080p: "url"
                    rf'video_{quality}\s*:\s*["\'](https?://[^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                ]

                for pattern in patterns:
                    match = re.search(pattern, html, re.IGNORECASE)
                    if match:
                        stream_url = match.group(1).replace('\\/', '/')
                        if '.m3u8' in stream_url:
                            is_hls = True
                        height = int(quality.replace('p', ''))
                        width = int(height * 16 / 9)
                        logger.info(f"[WHORESHUB_FAST] Found {quality} URL via regex (HLS={is_hls})")
                        break

                if stream_url:
                    break  # Exit quality loop once we find any quality
                    
            # Strategy 1.5: FAST - Check for KVS style variables (video_url, video_alt_url)
            if not stream_url:
                best_height = 0
                for k in ['video_url', 'video_alt_url', 'video_alt_url2', 'video_alt_url3', 'video_alt_url4']:
                    m_url = re.search(rf"{k}:\s*'(https?://[^']+)'", html)
                    m_text = re.search(rf"{k}_text:\s*'([^']+)'", html)
                    if m_url:
                        url = m_url.group(1)
                        if '.m3u8' in url:
                            is_hls = True
                        h = 720
                        if m_text:
                            text = m_text.group(1)
                            if '2160' in text or '4K' in text.upper(): h = 2160
                            elif '1440' in text: h = 1440
                            elif '1080' in text: h = 1080
                            elif '720' in text: h = 720
                            elif '480' in text: h = 480
                            elif '360' in text: h = 360
                            
                        if h > best_height:
                            best_height = h
                            stream_url = url
                            height = h
                            width = int(h * 16 / 9)
                            logger.info(f"[WHORESHUB_FAST] Found URL via KVS {k} ({h}p)")

            # Strategy 2: FAST - Find any MP4 or M3U8 URL in HTML (MOVED UP - was Strategy 3)
            if not stream_url:
                video_matches = re.findall(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)', html)
                if video_matches:
                    # Try to find highest quality by checking URL for quality indicators
                    for video_url in video_matches:
                        if '2160' in video_url or '4k' in video_url.lower():
                            stream_url = video_url
                            height = 2160
                            width = 3840
                            logger.info(f"[WHORESHUB_FAST] Found 4K URL via MP4 search")
                            break
                        elif '1440' in video_url:
                            stream_url = video_url
                            height = 1440
                            width = 2560
                            logger.info(f"[WHORESHUB_FAST] Found 1440p URL via MP4 search")
                            break
                        elif '1080' in video_url:
                            stream_url = video_url
                            height = 1080
                            width = 1920
                            logger.info(f"[WHORESHUB_FAST] Found 1080p URL via MP4 search")
                            break
                        elif '720' in video_url:
                            stream_url = video_url
                            height = 720
                            width = 1280
                            logger.info(f"[WHORESHUB_FAST] Found 720p URL via MP4 search")
                            break

                    # If no quality found in URL, use first match with default
                    if not stream_url and video_matches:
                        stream_url = video_matches[0]
                        height = 720  # Default assumption when quality not in URL
                        width = 1280
                        logger.info(f"[WHORESHUB_FAST] Found MP4/M3U8 URL (quality unknown, defaulting to 720p)")

                    if stream_url and '.m3u8' in stream_url:
                        is_hls = True

            # Strategy 3: Check for embedded iframes (Streamtape, Dood, etc.) - MOVED DOWN
            # Only use this if we couldn't find direct video URLs
            if not stream_url:
                iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if iframe_match:
                    iframe_src = iframe_match.group(1)
                    logger.info(f"[WHORESHUB_FAST] Found embedded player: {iframe_src}")

                    # Try to detect quality from iframe URL or surrounding context
                    quality_detected = False

                    # Check iframe URL for quality hints
                    if '2160' in iframe_src or '4k' in iframe_src.lower():
                        height = 2160
                        width = 3840
                        quality_detected = True
                        logger.info(f"[WHORESHUB_FAST] Detected 4K from iframe URL")
                    elif '1440' in iframe_src:
                        height = 1440
                        width = 2560
                        quality_detected = True
                        logger.info(f"[WHORESHUB_FAST] Detected 1440p from iframe URL")
                    elif '1080' in iframe_src or 'fhd' in iframe_src.lower():
                        height = 1080
                        width = 1920
                        quality_detected = True
                        logger.info(f"[WHORESHUB_FAST] Detected 1080p from iframe URL")
                    elif '720' in iframe_src or 'hd' in iframe_src.lower():
                        height = 720
                        width = 1280
                        quality_detected = True
                        logger.info(f"[WHORESHUB_FAST] Detected 720p from iframe URL")

                    # If not in URL, check surrounding HTML context (200 chars before/after)
                    if not quality_detected:
                        context_start = max(0, iframe_match.start() - 200)
                        context_end = min(len(html), iframe_match.end() + 200)
                        context = html[context_start:context_end]

                        if '2160' in context or '4K' in context.upper():
                            height = 2160
                            width = 3840
                            logger.info(f"[WHORESHUB_FAST] Detected 4K from iframe context")
                        elif '1440' in context:
                            height = 1440
                            width = 2560
                            logger.info(f"[WHORESHUB_FAST] Detected 1440p from iframe context")
                        elif '1080' in context or 'FHD' in context.upper():
                            height = 1080
                            width = 1920
                            logger.info(f"[WHORESHUB_FAST] Detected 1080p from iframe context")
                        elif '720' in context or 'HD' in context.upper():
                            height = 720
                            width = 1280
                            logger.info(f"[WHORESHUB_FAST] Detected 720p from iframe context")
                        else:
                            # Fallback: default to 720p
                            height = 720
                            width = 1280
                            logger.info(f"[WHORESHUB_FAST] No quality detected for iframe, defaulting to 720p")

                    stream_url = iframe_src

            # Strategy 4: SLOW FALLBACK - Parse video tag sources (only if regex failed)
            if not stream_url:
                logger.info(f"[WHORESHUB_FAST] Regex extraction failed, trying video tag parsing...")
                # Only create BeautifulSoup now if we really need it
                if soup is None:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, 'html.parser')

                video_tag = soup.find('video')
                if video_tag:
                    source_tags = video_tag.find_all('source')
                    best_source = None
                    best_height = 0

                    for source in source_tags:
                        src = source.get('src')
                        src_type = source.get('type', '').lower()
                        label = source.get('label', '').lower()
                        res = source.get('res', '').lower()

                        if src:
                            # Check if HLS
                            if '.m3u8' in src or 'application/x-mpegurl' in src_type:
                                is_hls = True

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
                        height = best_height if best_height > 0 else 720
                        width = int(height * 16 / 9)
                        logger.info(f"[WHORESHUB_FAST] Found URL via video tag: {height}p (HLS={is_hls})")

            if not stream_url:
                logger.error(f"[WHORESHUB_FAST] No stream URL found for {url}")
                # Try yt-dlp as fallback for embedded players
                logger.info(f"[WHORESHUB_FAST] Attempting yt-dlp extraction as fallback...")
                try:
                    import yt_dlp
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'ignoreerrors': True,
                        'socket_timeout': 15,
                        'retries': 2,
                        'format': 'best'
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info and info.get('url'):
                            stream_url = info['url']
                            height = info.get('height', 720)
                            width = info.get('width', 1280)
                            if info.get('duration'):
                                duration = int(info['duration'])
                            logger.info(f"[WHORESHUB_FAST] yt-dlp extracted: {height}p")
                        else:
                            logger.error(f"[WHORESHUB_FAST] yt-dlp returned no URL")
                            return None
                except Exception as e:
                    logger.error(f"[WHORESHUB_FAST] yt-dlp extraction failed: {e}")
                    return None

            # Extract views - FAST regex
            views = 0
            views_match = re.search(r'(\d+(?:,\d+)*)\s*views?', html, re.IGNORECASE)
            if views_match:
                try:
                    views = int(views_match.group(1).replace(',', ''))
                except:
                    pass

            # Extract tags - FAST regex
            tags = []
            tags_matches = re.findall(r'(?:class=["\'](?:tag|category)[^>]*>|/tags?/[^"\'<>]+["\'])[^>]*>([^<]+)</a>', html, re.IGNORECASE)
            if tags_matches:
                tags = [tag.strip() for tag in tags_matches if tag.strip()]

            # Extract uploader - FAST regex
            uploader = ""
            uploader_match = re.search(r'(?:uploader|author|user|channel)[^>]*>([^<]+)</a>', html, re.IGNORECASE)
            if uploader_match:
                uploader = uploader_match.group(1).strip()

            logger.info(f"[WHORESHUB_FAST] Successfully extracted: {title} ({height}p, HLS={is_hls}) in ~{int((resp.elapsed.total_seconds())*1000)}ms")

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
                "views": views,
                "upload_date": None,
                "uploader": uploader,
                "is_hls": is_hls,
                "size_bytes": size_bytes
            }

        except Exception as e:
            logger.error(f"[WHORESHUB] Extraction failed for {url}: {e}", exc_info=True)
            return None
