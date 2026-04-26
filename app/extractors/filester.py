import logging
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .base import VideoExtractor

logger = logging.getLogger(__name__)


def _guess_resolution_from_name(name: str):
    """Extract width/height hints from filename like 2160p, 1080p, 720p."""
    t = (name or "").upper()
    if re.search(r'\b(4K|2160P|UHD)\b', t):
        return 3840, 2160
    if re.search(r'\b(1440P|2K)\b', t):
        return 2560, 1440
    if re.search(r'\b(1080P|FHD)\b', t):
        return 1920, 1080
    if re.search(r'\b(720P|HD)\b', t):
        return 1280, 720
    if re.search(r'\b(480P)\b', t):
        return 854, 480
    if re.search(r'\b(360P)\b', t):
        return 640, 360
    return 0, 0


def _parse_duration(text: str) -> float:
    """Parse 'HH:MM:SS' or 'MM:SS' string into seconds."""
    if not text:
        return 0.0
    parts = text.strip().split(":")
    try:
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return float(parts[0])
    except Exception:
        pass
    return 0.0


def _parse_size_bytes(text: str) -> int:
    """Parse '5.27 GB', '320 MB' etc. into bytes."""
    if not text:
        return 0
    m = re.search(r'([\d.]+)\s*(TB|GB|MB|KB|B)\b', text, re.I)
    if not m:
        return 0
    n = float(m.group(1))
    u = m.group(2).upper()
    mult = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    return int(n * mult.get(u, 1))


class FilesterExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Filester"

    def can_handle(self, url: str) -> bool:
        u = (url or "").lower()
        return "filester." in u and "/d/" in u

    @staticmethod
    def _extract_slug(url: str) -> Optional[str]:
        m = re.search(r"/d/([A-Za-z0-9_-]+)", url or "", re.I)
        return m.group(1) if m else None

    @staticmethod
    def _cache_origin_from_page(url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        # Filester uses cache1.filester.me for the CDN, even if the main site is filester.gg
        return f"{scheme}://cache1.filester.me"

    @staticmethod
    def _scrape_page_meta(html: str, page_url: str) -> dict:
        """Extract title, thumbnail, duration, size from Filester HTML page."""
        soup = BeautifulSoup(html, "html.parser")
        meta = {}

        # --- Title ---
        # Filester puts the actual filename as the <title> (before " | filester")
        title = ""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            # "SheLovesBlack.2024.mp4 | filester.me" -> "SheLovesBlack.2024.mp4"
            title = re.split(r'\s*[|\-]\s*filester', title_tag.string, flags=re.I)[0].strip()

        # Fallback: og:title
        if not title:
            og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
            if og:
                title = re.split(r'\s*[|\-]\s*filester', og.get("content", ""), flags=re.I)[0].strip()

        # Fallback: first h1/h2 that doesn't contain "filester" brand
        if not title or "filester" in title.lower():
            for tag in soup.find_all(["h1", "h2", "h3"]):
                t = tag.get_text(strip=True)
                if t and "filester" not in t.lower() and len(t) > 3:
                    title = t
                    break

        meta["title"] = title

        # --- Thumbnail ---
        thumb = ""
        og_img = soup.find("meta", property="og:image")
        if og_img:
            thumb = og_img.get("content", "").strip()
        if not thumb:
            vid = soup.find("video", poster=True)
            if vid:
                thumb = vid.get("poster", "").strip()
        if thumb and thumb.startswith("//"):
            thumb = "https:" + thumb
        meta["thumbnail"] = thumb

        # --- Duration ---
        # Video player duration is in the <video> element or in a time display element
        duration = 0.0
        vid_el = soup.find("video")
        if vid_el and vid_el.get("data-duration"):
            try:
                duration = float(vid_el["data-duration"])
            except Exception:
                pass
        if not duration:
            # Look for a time text like "33:58" or "1:33:58" in page
            time_els = soup.find_all(string=re.compile(r'^\s*\d{1,2}:\d{2}(:\d{2})?\s*$'))
            for t in time_els:
                d = _parse_duration(t.strip())
                if d > 0:
                    duration = d
                    break
        if not duration:
            # og:video:duration (seconds)
            og_dur = soup.find("meta", property="og:video:duration")
            if og_dur:
                try:
                    duration = float(og_dur.get("content", 0))
                except Exception:
                    pass
        meta["duration"] = duration

        # --- File size ---
        size_bytes = 0
        # Look for text like "5.27 GB" anywhere on page
        body_text = soup.get_text(" ", strip=True)
        m = re.search(r'([\d.]+)\s*(TB|GB|MB|KB)\b', body_text, re.I)
        if m:
            size_bytes = _parse_size_bytes(m.group(0))
        meta["size_bytes"] = size_bytes

        # --- Resolution from filename ---
        width, height = _guess_resolution_from_name(meta.get("title", ""))
        meta["width"] = width
        meta["height"] = height

        return meta

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        slug = self._extract_slug(url)
        if not slug:
            return None

        parsed = urlparse(url)
        page_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://filester.me"
        cache_origin = self._cache_origin_from_page(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": url,
            "Origin": page_origin,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        stream_url = None
        page_meta = {}

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, verify=False) as client:
                # 1. Fetch the page HTML for metadata
                page_resp = await client.get(url, headers=headers)
                if page_resp.status_code == 200:
                    page_meta = self._scrape_page_meta(page_resp.text, url)

                # 2. Call token API for stream URL
                api_url = f"{page_origin}/api/public/view"
                api_headers = {**headers, "Content-Type": "application/json", "Accept": "application/json, text/plain, */*"}
                api_resp = await client.post(api_url, json={"file_slug": slug}, headers=api_headers)

                if api_resp.status_code == 200 and api_resp.content:
                    data = api_resp.json()
                    view_url = data.get("view_url") or data.get("url") or data.get("stream_url")
                    if view_url:
                        if view_url.startswith("http://") or view_url.startswith("https://"):
                            stream_url = view_url
                        else:
                            stream_url = f"{cache_origin}{view_url}"

                # 3. Fallback: look for direct MP4/stream link in page HTML
                if not stream_url and page_resp.status_code == 200:
                    soup = BeautifulSoup(page_resp.text, "html.parser")
                    # Check <video src> or <source src>
                    for sel in ['video source[src]', 'video[src]', 'source[src]']:
                        el = soup.select_one(sel)
                        if el:
                            s = el.get("src", "")
                            if s and not s.startswith("blob:"):
                                stream_url = ("https:" + s) if s.startswith("//") else s
                                break
                    # Check for cache CDN links in script/JSON embedded in page
                    if not stream_url:
                        for pattern in [
                            r'(https?://cache\d*\.filester\.[a-z]+/[^"\'\\s<>]+\.(?:mp4|mkv|webm)(?:\?[^"\'\\s<>]*)?)',
                            r'"(https?://[^"]+\.(?:mp4|mkv|webm)(?:\?[^"]+)?)"',
                        ]:
                            m = re.search(pattern, page_resp.text, re.I)
                            if m:
                                stream_url = m.group(1)
                                break

        except Exception as e:
            logger.error("Filester extraction failed for %s: %s", url, e)
            return None

        if not stream_url:
            logger.warning("Filester: no stream URL found for %s", url)
            return None

        title = page_meta.get("title") or slug
        width = page_meta.get("width", 0)
        height = page_meta.get("height", 0)

        return {
            "id": slug,
            "title": title,
            "description": "",
            "thumbnail": page_meta.get("thumbnail", ""),
            "duration": page_meta.get("duration", 0),
            "stream_url": stream_url,
            "width": width,
            "height": height,
            "size_bytes": page_meta.get("size_bytes", 0),
            "tags": [],
            "uploader": "Filester",
            "is_hls": False,
        }
