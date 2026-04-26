"""
WhoresHub Discovery Module
Smart discovery and import system for WhoresHub videos with advanced filtering.
"""
import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_from_listing(container, video_url: str, thumbnail_map: Dict[str, str] = None) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from a video container element.
    
    Args:
        container: BeautifulSoup element (the div.thumb or similar)
        video_url: Full video page URL
        thumbnail_map: Optional dictionary mapping video IDs/URLs to thumbnail URLs
        
    Returns:
        Video metadata dict or None
    """
    try:
        if thumbnail_map is None:
            thumbnail_map = {}

        # Extract title - try multiple sources
        title = None
        
        # Method 1: Find link with title
        link = container.find('a', href=True)
        if link and link.get('title'):
            title = link.get('title').strip()
            
        # Method 2: Find description span
        if not title:
            desc_elem = container.find(['span', 'div'], class_=re.compile(r'description|title', re.IGNORECASE))
            if desc_elem:
                title = desc_elem.get_text().strip()
                
        # Method 3: alt text on image
        if not title:
            img = container.find('img')
            if img and img.get('alt'):
                title = img.get('alt').strip()
                
        # Method 4: Extract from URL
        if not title:
            parts = video_url.split('/')
            if len(parts) > 3:
                title_slug = parts[-1] if parts[-1] else parts[-2]
                title = title_slug.replace('-', ' ').replace('_', ' ').title()
        
        if not title:
            title = "WhoresHub Video"

        # Extract thumbnail
        thumbnail = None
        
        # Strategy 0: Check thumbnail map
        if thumbnail_map:
            for key in thumbnail_map:
                if key in video_url or video_url in key:
                    thumbnail = thumbnail_map[key]
                    break

        # Strategy 1: Check img tag
        if not thumbnail:
            img = container.find('img')
            if img:
                # Check ALL common lazy-load attributes
                thumbnail = (
                    img.get('data-src') or 
                    img.get('data-original') or 
                    img.get('data-lazy-src') or 
                    img.get('data-lazy') or 
                    img.get('data-thumb') or 
                    img.get('src')
                )
                
                # Skip placeholders
                if thumbnail and ('placeholder' in thumbnail.lower() or 'data:image' in thumbnail or 'blank.gif' in thumbnail):
                    thumbnail = None
                    # Try to find other images if this was a placeholder
                    other_imgs = container.find_all('img')
                    for other_img in other_imgs:
                        other_thumb = other_img.get('data-src') or other_img.get('data-original') or other_img.get('src')
                        if other_thumb and 'placeholder' not in other_thumb.lower() and 'data:image' not in other_thumb:
                            thumbnail = other_thumb
                            break

        # Clean up thumbnail URL
        if thumbnail:
            thumbnail = thumbnail.strip()
            if thumbnail.startswith('//'):
                thumbnail = f"https:{thumbnail}"
            elif not thumbnail.startswith('http'):
                thumbnail = f"https://whoreshub.com{thumbnail if thumbnail.startswith('/') else '/' + thumbnail}"

        # Extract duration - look for specific classes
        duration = 0
        duration_elem = container.find(['span', 'div', 'time'], class_=re.compile(r'duration|time|length', re.IGNORECASE))
        if duration_elem:
            duration_text = duration_elem.get_text().strip()
            # Match 00:00 or 0:00:00
            time_match = re.search(r'(\d+):(\d+)(?::(\d+))?', duration_text)
            if time_match:
                if time_match.group(3):  # HH:MM:SS
                    duration = int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + int(time_match.group(3))
                else:  # MM:SS
                    duration = int(time_match.group(1)) * 60 + int(time_match.group(2))

        # Extract quality
        resolution = 720
        quality_str = "720p"
        quality_elem = container.find(['span', 'div'], class_=re.compile(r'quality|hd|is-hd|badge', re.IGNORECASE))
        if quality_elem:
            quality_text = quality_elem.get_text().strip().upper()
            if '2160' in quality_text or '4K' in quality_text:
                resolution = 2160
                quality_str = "4K"
            elif '1080' in quality_text:
                resolution = 1080
                quality_str = "1080p"
            elif '720' in quality_text or 'HD' in quality_text:
                resolution = 720
                quality_str = "720p"

        # Extract views
        views = 0
        views_elem = container.find(['span', 'div'], class_=re.compile(r'views?|watch', re.IGNORECASE))
        if views_elem:
            views_text = views_elem.get_text().strip()
            views_match = re.search(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*([KMB])?', views_text, re.IGNORECASE)
            if views_match:
                try:
                    num = float(views_match.group(1).replace(',', ''))
                    multiplier = views_match.group(2)
                    if multiplier:
                        mult_upper = multiplier.upper()
                        if mult_upper == 'K': num *= 1000
                        elif mult_upper == 'M': num *= 1000000
                    views = int(num)
                except: pass

        upload_type = "studio"
        if '/user/' in video_url or '/users/' in video_url or '/amateur/' in video_url:
            upload_type = "user"

        return {
            "url": video_url,
            "title": title,
            "thumbnail": thumbnail,
            "duration": duration,
            "quality": quality_str,
            "resolution": resolution,
            "views": views,
            "upload_type": upload_type,
            "stream_url": None
        }
    except Exception as e:
        logger.error(f"[WHORESHUB_DISCOVERY] Extraction failed: {e}")
        return None



def _passes_filters(video: Dict[str, Any], min_quality: int, min_duration: int, upload_type: str, keyword: str = "") -> bool:
    """
    Check if video passes all filter criteria.
    NOTE: For discovery mode, we're lenient on quality/duration since listing pages
    may not have complete metadata. The actual filtering happens during import.

    Args:
        video: Video metadata dict
        min_quality: Minimum resolution (e.g., 720, 1080)
        min_duration: Minimum duration in seconds
        upload_type: "all", "user", or "studio"
        keyword: Optional keyword filter

    Returns:
        True if video passes all filters
    """
    # Must have URL
    if not video.get('url'):
        return False

    # Quality filter - LENIENT: Only filter out if we KNOW it's below minimum
    # If resolution is 0 or default (720), let it through - we'll check during import
    resolution = video.get('resolution', 0)
    if resolution > 0 and resolution < min_quality:
        # Only filter if we have explicit resolution data that's below minimum
        # Exception: If resolution is exactly 720 (default), let it through
        if resolution != 720:
            return False

    # Duration filter - LENIENT: Only filter if we KNOW it's too short
    # If duration is 0, let it through - we'll check during import
    duration = video.get('duration', 0)
    if duration > 0 and duration < min_duration:
        return False

    # Upload type filter - STRICT: This can be determined from URL
    if upload_type != "all":
        if video.get('upload_type') != upload_type:
            return False

    # Keyword filter - not applicable if already searched by keyword
    # Skip this filter since the search already includes the keyword

    return True


def scrape_whoreshub_discovery(
    keyword: str = "",
    tag: str = "",
    min_quality: int = 720,
    min_duration: int = 300,  # 5 minutes default
    pages: int = 1,
    upload_type: str = "all",
    auto_skip_low_quality: bool = True
) -> List[Dict[str, Any]]:
    """
    Discover videos from WhoresHub with filtering.

    Args:
        keyword: Search keyword (optional)
        tag: Tag/category to search (optional)
        min_quality: Minimum resolution (720, 1080, 1440, 2160)
        min_duration: Minimum duration in seconds
        pages: Number of pages to scan (1-10)
        upload_type: "all", "user", or "studio"
        auto_skip_low_quality: Skip videos below min_quality automatically

    Returns:
        List of video metadata dictionaries
    """
    logger.info(f"[WHORESHUB_DISCOVERY] Starting scrape: keyword='{keyword}', tag='{tag}', min_quality={min_quality}p, pages={pages}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://whoreshub.com/'
    }

    # Determine base URL based on search type
    base_url = None

    if keyword:
        # Search by keyword: /search/{keyword}/
        search_slug = keyword.strip().lower().replace(' ', '-')
        base_url = f"https://whoreshub.com/search/{search_slug}/"
        logger.info(f"[WHORESHUB_DISCOVERY] Mode: SEARCH | Query: '{keyword}'")

    elif tag:
        # Search by tag: /tags/{tag}/ or /category/{tag}/
        tag_slug = tag.strip().lower().replace(' ', '-')
        # Try tags first, then categories
        base_url = f"https://whoreshub.com/tags/{tag_slug}/"
        logger.info(f"[WHORESHUB_DISCOVERY] Mode: TAG | Tag: '{tag}'")

    else:
        # Latest videos
        base_url = "https://whoreshub.com/"
        logger.info(f"[WHORESHUB_DISCOVERY] Mode: LATEST")

    all_videos = []
    seen_urls = set()  # Track globally across all pages to avoid duplicates
    pages = min(max(1, pages), 10)  # Clamp between 1-10

    for page_num in range(1, pages + 1):
        try:
            # Construct page URL
            if page_num == 1:
                page_url = base_url
            else:
                # WhoresHub typically uses ?page= or /page/{num}/
                if '?' in base_url:
                    page_url = f"{base_url}&page={page_num}"
                else:
                    # Try both formats
                    page_url = f"{base_url}?page={page_num}"

            logger.info(f"[WHORESHUB_DISCOVERY] Fetching page {page_num}: {page_url}")

            resp = requests.get(page_url, headers=headers, timeout=15, allow_redirects=True)

            if resp.status_code != 200:
                logger.error(f"[WHORESHUB_DISCOVERY] Page {page_num} returned status {resp.status_code}")
                logger.error(f"[WHORESHUB_DISCOVERY] Final URL after redirects: {resp.url}")
                continue

            logger.info(f"[WHORESHUB_DISCOVERY] Successfully fetched page {page_num} (status {resp.status_code})")

            soup = BeautifulSoup(resp.text, 'html.parser')

            # EXPERIMENTAL: Try to extract thumbnail mapping from page JavaScript
            thumbnail_map = {}
            try:
                # Look for JSON data in script tags that might contain video metadata
                for script in soup.find_all('script'):
                    script_text = script.string if script.string else ""
                    # Look for patterns like: {"thumb":"url", "id":"123"} or similar
                    json_matches = re.findall(r'\{[^{}]*"thumb[^:]*":\s*"([^"]+)"[^{}]*"(?:id|url|href)[^:]*":\s*"([^"]+)"[^{}]*\}', script_text, re.IGNORECASE)
                    for thumb_url, video_id in json_matches:
                        if thumb_url and video_id:
                            thumbnail_map[video_id] = thumb_url
                            logger.debug(f"[WHORESHUB_DISCOVERY] Found thumbnail in JS: {video_id[:30]} -> {thumb_url[:50]}")
                logger.info(f"[WHORESHUB_DISCOVERY] Extracted {len(thumbnail_map)} thumbnails from JavaScript")
            except Exception as e:
                logger.warning(f"[WHORESHUB_DISCOVERY] Failed to extract thumbnails from JS: {e}")

            # Find video cards/containers
            video_cards = soup.find_all('div', class_=re.compile(r'thumb|item|video-card', re.IGNORECASE))
            
            # If no containers found, fallback to links (legacy mode)
            if not video_cards:
                logger.warning(f"[WHORESHUB_DISCOVERY] No containers found, falling back to link-based search")
                links = soup.find_all('a', href=re.compile(r'/videos?/'))
                # Group by URL to avoid duplicates
                unique_links = {}
                for l in links:
                    url = l.get('href')
                    if url and url not in unique_links:
                        unique_links[url] = l
                video_cards = list(unique_links.values())

            logger.info(f"[WHORESHUB_DISCOVERY] Found {len(video_cards)} potential videos on page {page_num}")

            page_videos = []
            for card in video_cards:
                # Find the main video link within the card
                link = card if card.name == 'a' else card.find('a', href=re.compile(r'/videos?/'))
                if not link:
                    continue
                    
                href = link.get('href', '')
                if not href:
                    continue

                # Build full URL
                if href.startswith('http'):
                    video_url = href
                elif href.startswith('/'):
                    video_url = f"https://whoreshub.com{href}"
                else:
                    continue

                # Skip if already seen
                if video_url in seen_urls:
                    continue
                seen_urls.add(video_url)

                # Extract metadata from card
                metadata = _extract_from_listing(card, video_url, thumbnail_map)
                if metadata:
                    all_videos.append(metadata)
                    page_videos.append(metadata)
                    thumb_status = "✓" if metadata.get('thumbnail') else "✗"
                    duration_status = "✓" if metadata.get('duration') else "✗"
                    logger.debug(f"[WHORESHUB_DISCOVERY] Added: {metadata.get('title', '')[:30]} | Thumb: {thumb_status} | Dur: {duration_status}")

            logger.info(f"[WHORESHUB_DISCOVERY] Extracted {len(page_videos)} videos from page {page_num}")

        except Exception as e:
            logger.error(f"[WHORESHUB_DISCOVERY] Error on page {page_num}: {e}", exc_info=True)
            continue

    # Apply filters
    filtered_results = []
    for video in all_videos:
        if _passes_filters(video, min_quality, min_duration, upload_type, keyword):
            filtered_results.append(video)

    # Count thumbnail success rate
    total_thumbs = sum(1 for v in filtered_results if v.get('thumbnail'))
    thumb_rate = (total_thumbs / len(filtered_results) * 100) if filtered_results else 0

    logger.info(f"[WHORESHUB_DISCOVERY] Scraping complete. Found {len(filtered_results)} matching videos after filters")
    logger.info(f"[WHORESHUB_DISCOVERY] Total videos scraped: {len(all_videos)}, Passed filters: {len(filtered_results)}")
    logger.info(f"[WHORESHUB_DISCOVERY] Thumbnails extracted: {total_thumbs}/{len(filtered_results)} ({thumb_rate:.1f}%)")

    return filtered_results
