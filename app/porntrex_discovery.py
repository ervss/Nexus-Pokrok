"""
Porntrex Discovery Module
Smart discovery and import system for Porntrex videos with advanced filtering.
"""
import re
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_from_listing(link_element, video_url: str) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from a video listing element (thumbnail card).
    This is faster than fetching each video page individually.

    Args:
        link_element: BeautifulSoup element (the <a> tag or parent)
        video_url: Full video page URL

    Returns:
        Video metadata dict or None
    """
    try:
        # Find parent container (might be the link itself or a parent div)
        container = link_element.parent if link_element.parent else link_element

        # Extract title - try multiple sources
        title = None

        # Method 1: title attribute on link
        if link_element.get('title'):
            title = link_element.get('title').strip()

        # Method 2: Find title in nearby text
        if not title:
            title_elem = container.find(['h2', 'h3', 'h4', 'div'], class_=re.compile(r'title', re.IGNORECASE))
            if title_elem:
                title = title_elem.get_text().strip()

        # Method 3: alt text on image
        if not title:
            img = link_element.find('img')
            if img and img.get('alt'):
                title = img.get('alt').strip()

        # Method 4: Extract from URL
        if not title:
            # URL format: /video/12345/title-here
            parts = video_url.split('/')
            if len(parts) > 4:
                title_slug = parts[-1] if parts[-1] else parts[-2]
                title = title_slug.replace('-', ' ').title()

        if not title:
            title = "Porntrex Video"

        # Extract thumbnail
        thumbnail = None
        img = link_element.find('img')
        if img:
            thumbnail = img.get('data-src') or img.get('src') or img.get('data-lazy-src') or img.get('data-original')
            if thumbnail:
                # Clean up thumbnail URL
                thumbnail = thumbnail.strip()
                # Handle protocol-relative URLs
                if thumbnail.startswith('//'):
                    thumbnail = f"https:{thumbnail}"
                # Handle relative URLs
                elif not thumbnail.startswith('http'):
                    thumbnail = f"https://www.porntrex.com{thumbnail}" if thumbnail.startswith('/') else None
                # Validate it's a real URL
                if thumbnail and not (thumbnail.startswith('http://') or thumbnail.startswith('https://')):
                    thumbnail = None

        logger.debug(f"[PORNTREX_DISCOVERY] Extracted thumbnail for {video_url[:50]}: {thumbnail[:80] if thumbnail else 'None'}")

        # Extract duration from container
        duration = 0
        duration_elem = container.find(['span', 'div'], class_=re.compile(r'duration|time|length', re.IGNORECASE))
        if duration_elem:
            duration_text = duration_elem.get_text().strip()
            # Parse MM:SS or HH:MM:SS
            time_match = re.search(r'(\d+):(\d+)(?::(\d+))?', duration_text)
            if time_match:
                if time_match.group(3):  # HH:MM:SS
                    duration = int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + int(time_match.group(3))
                else:  # MM:SS
                    duration = int(time_match.group(1)) * 60 + int(time_match.group(2))

        # Extract quality/resolution - be more flexible
        resolution = 720  # Default to 720p instead of 0
        quality_str = "720p"
        quality_elem = container.find(['span', 'div'], class_=re.compile(r'quality|hd|resolution', re.IGNORECASE))
        if quality_elem:
            quality_text = quality_elem.get_text().strip().upper()
            if '2160' in quality_text or '4K' in quality_text:
                resolution = 2160
                quality_str = "2160p"
            elif '1440' in quality_text:
                resolution = 1440
                quality_str = "1440p"
            elif '1080' in quality_text or 'FHD' in quality_text:
                resolution = 1080
                quality_str = "1080p"
            elif '720' in quality_text or 'HD' in quality_text:
                resolution = 720
                quality_str = "720p"
            elif '480' in quality_text:
                resolution = 480
                quality_str = "480p"
        else:
            # If no quality badge found, assume HD (most videos are at least 720p)
            resolution = 720
            quality_str = "720p"

        # Determine upload type
        is_user = '/user/' in video_url or '/users/' in video_url
        upload_type = "user" if is_user else "studio"

        # Extract views if available
        views = 0
        views_elem = container.find(text=re.compile(r'views?', re.IGNORECASE))
        if views_elem:
            views_match = re.search(r'([\d,]+)\s*views?', str(views_elem), re.IGNORECASE)
            if views_match:
                try:
                    views = int(views_match.group(1).replace(',', ''))
                except:
                    pass

        return {
            "title": title,
            "url": video_url,
            "thumbnail": thumbnail,
            "duration": duration,
            "quality": quality_str,
            "resolution": resolution,
            "upload_type": upload_type,
            "views": views,
            "stream_url": None,  # Will be extracted during import
            "source": "porntrex"
        }

    except Exception as e:
        logger.warning(f"[PORNTREX_DISCOVERY] Error extracting from listing for {video_url}: {e}")
        # Return basic metadata even if extraction fails
        return {
            "title": "Porntrex Video",
            "url": video_url,
            "thumbnail": None,
            "duration": 0,
            "quality": "720p",
            "resolution": 720,
            "upload_type": "studio",
            "views": 0,
            "stream_url": None,
            "source": "porntrex"
        }


def scrape_porntrex_discovery(
    keyword: str = "",
    min_quality: int = 1080,
    pages: int = 1,
    category: str = "",
    upload_type: str = "all",
    auto_skip_low_quality: bool = True
) -> List[Dict[str, Any]]:
    """
    Scrapes Porntrex search/category pages with concurrent video link fetching.

    Args:
        keyword: Search keyword (optional if category is provided)
        min_quality: Minimum resolution (720, 1080, 1440, 2160)
        pages: Number of pages to scan (1-10)
        category: Category slug (optional)
        upload_type: Filter by upload type ("all", "user", "studio")
        auto_skip_low_quality: Skip videos below min_quality

    Returns:
        List of video dictionaries with metadata and direct links
    """
    results = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.porntrex.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    # Determine base URL - Porntrex requires trailing slash!
    if category:
        # Category browsing: /categories/{category}/
        category_slug = category.strip().lower().replace(' ', '-')
        base_url = f"https://www.porntrex.com/categories/{category_slug}/"
        logger.info(f"[PORNTREX_DISCOVERY] Mode: CATEGORY | Category: '{category_slug}'")
    elif keyword:
        # Search format: /search/{keyword}/
        search_slug = keyword.strip().lower().replace(' ', '-')
        base_url = f"https://www.porntrex.com/search/{search_slug}/"
        logger.info(f"[PORNTREX_DISCOVERY] Mode: SEARCH | Query: '{search_slug}'")
    else:
        logger.error("[PORNTREX_DISCOVERY] Either keyword or category must be provided")
        return []

    logger.info(f"[PORNTREX_DISCOVERY] Starting scrape (min_quality={min_quality}p, pages={pages})")

    # Collect all video page URLs first
    video_page_urls = []
    seen_urls = set()  # Track globally across all pages

    for page_num in range(1, pages + 1):
        try:
            # Construct page URL - Porntrex uses ?page= parameter
            if page_num == 1:
                page_url = base_url
            else:
                page_url = f"{base_url}?page={page_num}"

            logger.info(f"[PORNTREX_DISCOVERY] Fetching page {page_num}: {page_url}")

            resp = requests.get(page_url, headers=headers, timeout=15, allow_redirects=True)

            if resp.status_code != 200:
                logger.error(f"[PORNTREX_DISCOVERY] Page {page_num} returned status {resp.status_code}")
                logger.error(f"[PORNTREX_DISCOVERY] Final URL after redirects: {resp.url}")
                continue

            logger.info(f"[PORNTREX_DISCOVERY] Successfully fetched page {page_num} (status {resp.status_code})")

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Find video containers - Try multiple patterns
            video_links = []

            # Strategy 1: Look for /video/ URLs with numbers
            video_links = soup.find_all('a', href=re.compile(r'/video/\d+'))

            # Strategy 2: Look for common video link patterns
            if not video_links:
                video_links = soup.find_all('a', href=re.compile(r'/videos?/'))

            # Strategy 3: Look for links with video-related classes
            if not video_links:
                video_links = soup.find_all('a', class_=re.compile(r'(thumb|video|item|card)', re.IGNORECASE))
                video_links = [link for link in video_links if link.get('href') and '/video' in link.get('href', '')]

            # Strategy 4: Look in specific containers
            if not video_links:
                containers = soup.find_all(['div', 'article'], class_=re.compile(r'(video|item|thumb|card)', re.IGNORECASE))
                for container in containers:
                    link = container.find('a', href=True)
                    if link and '/video' in link.get('href', ''):
                        video_links.append(link)

            # Strategy 5: Get all links and filter
            if not video_links:
                all_links = soup.find_all('a', href=True)
                video_links = [link for link in all_links if '/video' in link.get('href', '')]

            if not video_links:
                logger.warning(f"[PORNTREX_DISCOVERY] No videos found on page {page_num}")
                logger.debug(f"[PORNTREX_DISCOVERY] Page HTML preview: {resp.text[:500]}")
                continue

            # Extract metadata from listing page directly (faster approach)
            page_videos = []
            for link in video_links:
                href = link.get('href', '')
                if href and '/video/' in href:
                    full_url = href if href.startswith('http') else f"https://www.porntrex.com{href}"
                    if full_url not in seen_urls:
                        seen_urls.add(full_url)

                        # Extract metadata from the listing page element
                        metadata = _extract_from_listing(link, full_url)
                        if metadata:
                            video_page_urls.append(metadata)
                            page_videos.append(metadata)
                            logger.debug(f"[PORNTREX_DISCOVERY] Added video: {metadata.get('title', 'Unknown')} | Thumbnail: {metadata.get('thumbnail', 'None')[:50] if metadata.get('thumbnail') else 'None'}")

            logger.info(f"[PORNTREX_DISCOVERY] Found {len(page_videos)} videos on page {page_num} (Total so far: {len(video_page_urls)})")

        except Exception as e:
            logger.error(f"[PORNTREX_DISCOVERY] Error on page {page_num}: {e}")
            continue

    logger.info(f"[PORNTREX_DISCOVERY] Total videos extracted: {len(video_page_urls)}")

    # Apply filters
    filtered_results = []
    for video in video_page_urls:
        if _passes_filters(video, min_quality, upload_type, auto_skip_low_quality):
            filtered_results.append(video)
        else:
            logger.debug(f"[PORNTREX_DISCOVERY] Filtered: {video.get('title')} - Resolution: {video.get('resolution', 0)}")

    logger.info(f"[PORNTREX_DISCOVERY] Scraping complete. Found {len(filtered_results)} matching videos after filters")
    return filtered_results


def _fetch_video_details_concurrent(
    video_urls: List[str],
    headers: Dict[str, str],
    min_quality: int,
    upload_type: str,
    auto_skip_low_quality: bool,
    max_workers: int = 5
) -> List[Dict[str, Any]]:
    """
    Fetch video details from multiple video pages concurrently.

    Args:
        video_urls: List of video page URLs
        headers: HTTP headers
        min_quality: Minimum quality threshold
        upload_type: Filter by upload type
        auto_skip_low_quality: Skip low quality videos
        max_workers: Number of concurrent workers

    Returns:
        List of video metadata dictionaries
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_url = {
            executor.submit(_extract_video_metadata, url, headers): url
            for url in video_urls
        }

        # Process completed tasks
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                video_data = future.result()
                if video_data:
                    # Apply filters
                    if _passes_filters(video_data, min_quality, upload_type, auto_skip_low_quality):
                        results.append(video_data)
                        logger.info(f"[PORNTREX_DISCOVERY] ✓ {video_data['title']} ({video_data.get('quality', 'Unknown')})")
                    else:
                        logger.info(f"[PORNTREX_DISCOVERY] ✗ Filtered out: {video_data['title']} - Quality: {video_data.get('quality')}, Resolution: {video_data.get('resolution')}, Has stream: {bool(video_data.get('stream_url'))}")
                else:
                    logger.warning(f"[PORNTREX_DISCOVERY] ✗ No metadata extracted from {url}")
            except Exception as e:
                logger.error(f"[PORNTREX_DISCOVERY] Error processing {url}: {e}", exc_info=True)

    return results


def _extract_video_metadata(url: str, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    Extract metadata and direct video links from a single video page.

    Args:
        url: Video page URL
        headers: HTTP headers

    Returns:
        Video metadata dict or None
    """
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[PORNTREX_DISCOVERY] Video page {url} returned {resp.status_code}")
            return None

        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        # Extract title
        title = "Porntrex Video"
        title_tag = soup.find('h1', class_=re.compile(r'title|heading'))
        if title_tag:
            title = title_tag.get_text().strip()
        else:
            # Try meta title
            title_meta = soup.find('meta', property='og:title')
            if title_meta:
                title = title_meta.get('content', '').strip()

        # Extract thumbnail
        thumbnail = None
        thumb_meta = soup.find('meta', property='og:image')
        if thumb_meta:
            thumbnail = thumb_meta.get('content')
        else:
            # Try poster attribute
            video_tag = soup.find('video')
            if video_tag:
                thumbnail = video_tag.get('poster')

        # Extract duration
        duration = 0
        duration_meta = soup.find('meta', property='video:duration')
        if duration_meta:
            try:
                duration = int(duration_meta.get('content', 0))
            except:
                pass

        # If not in meta, try to find in page
        if duration == 0:
            duration_match = re.search(r'duration["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE)
            if duration_match:
                try:
                    duration = int(duration_match.group(1))
                except:
                    pass

        # Extract video sources - try multiple strategies
        stream_url = None
        quality_str = "SD"
        resolution = 480

        # Strategy 1: Look for video sources in HTML
        video_tag = soup.find('video')
        if video_tag:
            source_tags = video_tag.find_all('source')
            # Find highest quality source
            best_source = None
            best_height = 0

            for source in source_tags:
                src = source.get('src')
                label = source.get('label', '').lower()
                res = source.get('res', '').lower()

                if src:
                    # Try to determine quality
                    height = 0
                    if '2160' in label or '4k' in label or '2160' in res:
                        height = 2160
                    elif '1440' in label or '1440' in res:
                        height = 1440
                    elif '1080' in label or '1080' in res:
                        height = 1080
                    elif '720' in label or '720' in res:
                        height = 720
                    elif '480' in label or '480' in res:
                        height = 480

                    if height > best_height:
                        best_height = height
                        best_source = src

            if best_source:
                stream_url = best_source
                resolution = best_height if best_height > 0 else 480
                quality_str = f"{resolution}p"

        # Strategy 2: Look for video URLs in JavaScript/JSON
        if not stream_url:
            # Look for common patterns in HTML
            # Pattern: "1080p":"https://..."
            for quality in ['2160', '1440', '1080', '720', '480', '360']:
                pattern = rf'["\']?{quality}p?["\']?\s*:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']'
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    stream_url = match.group(1).replace('\\/', '/')
                    resolution = int(quality)
                    quality_str = f"{quality}p"
                    break

        # Strategy 3: Look for MP4 URLs directly
        if not stream_url:
            mp4_matches = re.findall(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html)
            if mp4_matches:
                # Pick the first one (usually highest quality)
                stream_url = mp4_matches[0]
                # Try to guess quality from URL
                if '1080' in stream_url:
                    resolution = 1080
                    quality_str = "1080p"
                elif '720' in stream_url:
                    resolution = 720
                    quality_str = "720p"

        # Determine upload type (user vs studio)
        is_user_upload = '/user/' in url.lower() or '/users/' in url.lower()
        upload_type = "user" if is_user_upload else "studio"

        # Extract views
        views = 0
        views_match = re.search(r'views?["\']?\s*[:=]\s*["\']?(\d+)', html, re.IGNORECASE)
        if views_match:
            try:
                views = int(views_match.group(1))
            except:
                pass

        return {
            "title": title,
            "url": url,
            "stream_url": stream_url,
            "thumbnail": thumbnail,
            "duration": duration,
            "quality": quality_str,
            "resolution": resolution,
            "upload_type": upload_type,
            "views": views,
            "source": "porntrex"
        }

    except Exception as e:
        logger.error(f"[PORNTREX_DISCOVERY] Error extracting {url}: {e}")
        return None


def _passes_filters(
    video: Dict[str, Any],
    min_quality: int,
    upload_type: str,
    auto_skip_low_quality: bool
) -> bool:
    """
    Check if video passes filter criteria.

    Args:
        video: Video metadata dict
        min_quality: Minimum quality threshold
        upload_type: Upload type filter ("all", "user", "studio")
        auto_skip_low_quality: Skip low quality

    Returns:
        True if video passes filters
    """
    # Quality filter
    if auto_skip_low_quality:
        resolution = video.get('resolution', 0)
        if resolution < min_quality:
            return False

    # Upload type filter
    if upload_type != "all":
        if video.get('upload_type') != upload_type:
            return False

    # Stream URL is optional for discovery - we'll extract it during import
    # Just having a valid URL is enough
    if not video.get('url'):
        return False

    return True
