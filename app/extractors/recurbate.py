import asyncio
import json
import logging
import os
import re
import time
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp

from .base import VideoExtractor

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class RecurbateExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Recurbate"

    def can_handle(self, url: str) -> bool:
        low = (url or "").lower()
        return "rec-ur-bate.com" in low or "recurbate.com" in low

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._extract_sync, url)

    def _extract_sync(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            page_url = self._normalize_url(url)
            if self._is_direct_media(page_url):
                return self._result(page_url, page_url, stream_url=page_url)

            html = self._get_text(page_url, self._headers(page_url))
            if not html:
                return self._try_ytdlp(page_url)

            metadata = self._extract_metadata(html, page_url)
            stream_url, height, size_bytes = self._extract_best_stream(html, page_url)
            player_url = self._extract_player_url(html, page_url)

            if player_url and not stream_url:
                player_html = self._get_text(player_url, self._headers(page_url))
                if player_html:
                    stream_url, height, size_bytes = self._extract_best_stream(player_html, player_url)
                    player_meta = self._extract_metadata(player_html, player_url)
                    metadata = {**player_meta, **metadata}

            if not stream_url:
                ytdlp = self._try_ytdlp(page_url)
                if ytdlp:
                    return ytdlp
                logger.warning("[Recurbate] no stream found for %s", page_url)
                return None

            return self._result(
                page_url,
                page_url,
                stream_url=stream_url,
                title=metadata.get("title") or "Recurbate Video",
                thumbnail=metadata.get("thumbnail") or "",
                duration=metadata.get("duration") or 0,
                width=metadata.get("width") or 0,
                height=height or metadata.get("height") or 0,
                size_bytes=size_bytes or metadata.get("size_bytes") or 0,
                tags=metadata.get("tags") or [],
                uploader=metadata.get("uploader") or "Recurbate",
            )
        except Exception as e:
            logger.error("[Recurbate] extract failed for %s: %s", url, e, exc_info=True)
            return None

    def _headers(self, referer: str = "") -> Dict[str, str]:
        origin = "https://rec-ur-bate.com"
        headers = {
            "User-Agent": UA,
            "Referer": referer or f"{origin}/",
            "Origin": origin,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        cookie = self._cookie_header_for_recurbate()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _get_text(self, url: str, headers: Dict[str, str]) -> str:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                logger.warning("[Recurbate] HTTP %s for %s", resp.status_code, url)
                return ""
            return resp.text
        except Exception as e:
            logger.debug("[Recurbate] request failed for %s: %s", url, e)
            return ""

    def _extract_metadata(self, html: str, page_url: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "title": "",
            "thumbnail": "",
            "duration": 0,
            "width": 0,
            "height": 0,
            "size_bytes": 0,
            "tags": [],
            "uploader": "",
        }

        for raw in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        ):
            for item in self._json_items(raw):
                out["title"] = item.get("name") or item.get("headline") or out["title"]
                out["thumbnail"] = self._first_url(item.get("thumbnailUrl") or item.get("thumbnail")) or out["thumbnail"]
                out["duration"] = self._parse_iso_duration(item.get("duration")) or out["duration"]
                out["width"] = self._int(item.get("width")) or out["width"]
                out["height"] = self._int(item.get("height")) or out["height"]
                out["size_bytes"] = self._parse_size(item.get("contentSize") or item.get("size")) or out["size_bytes"]
                uploader = item.get("author") or item.get("creator")
                if isinstance(uploader, dict):
                    uploader = uploader.get("name")
                out["uploader"] = uploader or out["uploader"]
                keywords = item.get("keywords")
                if isinstance(keywords, str):
                    out["tags"] = [t.strip() for t in keywords.split(",") if t.strip()]
                elif isinstance(keywords, list):
                    out["tags"] = [str(t).strip() for t in keywords if str(t).strip()]

        out["title"] = self._clean_title(
            out["title"] or self._meta(html, "og:title") or self._meta(html, "twitter:title") or self._title_tag(html)
        )
        out["thumbnail"] = self._normalize_media_url(
            out["thumbnail"] or self._meta(html, "og:image") or self._meta(html, "twitter:image"),
            page_url,
        )
        out["duration"] = out["duration"] or self._parse_duration_text(html)
        out["height"] = out["height"] or self._guess_height(out["title"] + " " + html[:4000])
        out["size_bytes"] = out["size_bytes"] or self._parse_size_text(html[:6000])
        if not out["tags"]:
            out["tags"] = self._extract_tags(html)
        if not out["uploader"]:
            out["uploader"] = self._extract_uploader(html)
        return out

    def _extract_best_stream(self, html: str, page_url: str) -> Tuple[str, int, int]:
        candidates: List[Tuple[int, int, str, int]] = []
        patterns = [
            r'["\'](https?://[^"\']+?\.(?:m3u8|mp4|webm)(?:\?[^"\']*)?)["\']',
            r'["\'](//[^"\']+?\.(?:m3u8|mp4|webm)(?:\?[^"\']*)?)["\']',
            r'(https?://[^"\'<>\s]+?\.(?:m3u8|mp4|webm)(?:\?[^"\'<>\s]*)?)',
            r'file\s*[:=]\s*["\']([^"\']+)["\']',
            r'(?:src|source|videoUrl|hls|mp4)\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4|webm)[^"\']*)["\']',
            r'<source[^>]+src=["\']([^"\']+)["\']',
            r'<video[^>]+src=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            for raw in re.findall(pattern, html, re.I):
                candidate = self._normalize_media_url(unescape(str(raw)).replace("\\/", "/"), page_url)
                if not self._is_usable_stream(candidate):
                    continue
                height = self._guess_height(candidate)
                size = self._nearby_size_bytes(html, raw)
                hls_rank = 10_000 if ".m3u8" in candidate.lower() else 0
                candidates.append((hls_rank + height, height, candidate, size))

        if not candidates:
            return "", 0, 0
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, height, url, size = candidates[0]
        return url, height, size

    def _extract_player_url(self, html: str, page_url: str) -> str:
        for pattern in (
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            r'["\']([^"\']*(?:embed|player)[^"\']*)["\']',
        ):
            for raw in re.findall(pattern, html, re.I):
                candidate = self._normalize_media_url(unescape(raw), page_url)
                if candidate.startswith("http") and self.can_handle(candidate):
                    return candidate
        return ""

    def _try_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "format": "best[protocol*=m3u8]/best[ext=mp4]/best",
                "http_headers": self._headers("https://rec-ur-bate.com/"),
            }
            for cookiefile in ("cookies.netscape.txt", "cookies.txt", "recurbate.cookies.txt"):
                if os.path.exists(cookiefile):
                    opts["cookiefile"] = cookiefile
                    break
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                return None
            stream_url = info.get("url")
            fmt = None
            if not stream_url and info.get("formats"):
                fmts = [f for f in info["formats"] if f.get("url")]
                fmts.sort(key=lambda f: ((1 if "m3u8" in str(f.get("protocol") or "") else 0), f.get("height") or 0), reverse=True)
                fmt = fmts[0] if fmts else None
                stream_url = fmt.get("url") if fmt else None
            if not stream_url:
                return None
            return self._result(
                url,
                url,
                stream_url=stream_url,
                title=info.get("title") or "Recurbate Video",
                thumbnail=info.get("thumbnail") or "",
                duration=float(info.get("duration") or 0),
                width=int((fmt or info).get("width") or 0),
                height=int((fmt or info).get("height") or 0),
                size_bytes=info.get("filesize") or info.get("filesize_approx") or (fmt or {}).get("filesize") or 0,
                tags=info.get("tags") or [],
            )
        except Exception as e:
            logger.debug("[Recurbate] yt-dlp failed for %s: %s", url, e)
            return None

    def _cookie_header_for_recurbate(self) -> str:
        """Build Cookie header from local Netscape cookie files when available."""
        for cookiefile in ("cookies.txt", "cookies.netscape.txt", "recurbate.cookies.txt"):
            if not os.path.exists(cookiefile):
                continue
            try:
                pairs: List[str] = []
                with open(cookiefile, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("\t")
                        if len(parts) < 7:
                            continue
                        domain, _flag, path, _secure, expiry, name, value = parts[:7]
                        d = (domain or "").lower()
                        if "rec-ur-bate.com" not in d and "recurbate.com" not in d:
                            continue
                        if expiry and expiry.isdigit() and int(expiry) > 0 and int(expiry) < int(time.time()):
                            continue
                        if name and value:
                            pairs.append(f"{name}={value}")
                if pairs:
                    return "; ".join(pairs)
            except Exception:
                continue
        return ""

    def _result(self, page_url: str, source_url: str, **kwargs: Any) -> Dict[str, Any]:
        stream_url = kwargs.get("stream_url") or page_url
        height = int(kwargs.get("height") or 0)
        width = int(kwargs.get("width") or self._width_for_height(height))
        size_bytes = int(kwargs.get("size_bytes") or 0)
        return {
            "id": self._id_from_url(page_url),
            "title": kwargs.get("title") or "Recurbate Video",
            "description": "",
            "thumbnail": kwargs.get("thumbnail") or "",
            "duration": float(kwargs.get("duration") or 0),
            "stream_url": stream_url,
            "width": width,
            "height": height,
            "filesize": size_bytes,
            "size_bytes": size_bytes,
            "tags": kwargs.get("tags") or [],
            "uploader": kwargs.get("uploader") or "Recurbate",
            "is_hls": ".m3u8" in stream_url.lower(),
            "source_url": source_url,
        }

    def _json_items(self, raw: str) -> List[Dict[str, Any]]:
        try:
            data = json.loads(unescape(raw).strip())
        except Exception:
            return []
        if isinstance(data, dict) and "@graph" in data and isinstance(data["@graph"], list):
            data = data["@graph"]
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def _normalize_url(self, url: str) -> str:
        if not url:
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return urljoin("https://rec-ur-bate.com/", url)
        return url

    def _normalize_media_url(self, url: str, base_url: str) -> str:
        if not url:
            return ""
        url = url.strip().strip('"\'')
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return urljoin(base_url, url)
        return url

    def _is_direct_media(self, url: str) -> bool:
        return urlparse(url).path.lower().endswith((".mp4", ".m4v", ".mov", ".mkv", ".webm", ".m3u8"))

    def _is_usable_stream(self, url: str) -> bool:
        low = (url or "").lower()
        if not low.startswith("http"):
            return False
        if any(x in low for x in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js", "thumbnail", "poster"]):
            return False
        return any(x in low for x in [".mp4", ".m3u8", ".webm"])

    def _meta(self, html: str, prop: str) -> str:
        patterns = [
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.I)
            if m:
                return unescape(m.group(1)).strip()
        return ""

    def _title_tag(self, html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        return re.sub(r"\s+", " ", unescape(m.group(1))).strip() if m else ""

    def _clean_title(self, title: str) -> str:
        title = re.sub(r"\s+", " ", unescape(title or "")).strip()
        title = re.sub(r"\s*[-|]\s*(rec-ur-bate|recurbate).*$", "", title, flags=re.I).strip()
        return title or "Recurbate Video"

    def _parse_iso_duration(self, value: Any) -> float:
        if not value or not isinstance(value, str):
            return 0
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value, re.I)
        if not m:
            return 0
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)

    def _parse_duration_text(self, html: str) -> float:
        text = re.sub(r"<[^>]+>", " ", html[:8000])
        m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
        if m:
            if m.group(3):
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            return int(m.group(1)) * 60 + int(m.group(2))
        total = 0
        for n, unit in re.findall(r"(\d+)\s*(hour|hours|hr|h|min|mins|minute|minutes|sec|secs|second|seconds|s)\b", text, re.I):
            value = int(n)
            unit = unit.lower()
            if unit.startswith(("h", "hr")):
                total += value * 3600
            elif unit.startswith(("m", "min")):
                total += value * 60
            else:
                total += value
        return total

    def _guess_height(self, text: str) -> int:
        m = re.search(r"(?<!\d)(2160|1440|1080|720|480|360)p?(?!\d)", text or "", re.I)
        return int(m.group(1)) if m else 0

    def _width_for_height(self, height: int) -> int:
        return {2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640}.get(height, 0)

    def _parse_size(self, value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        if not value:
            return 0
        m = re.search(r"([\d.]+)\s*(TB|GB|MB|KB|B)?", str(value).replace(",", "."), re.I)
        if not m:
            return 0
        mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        return int(float(m.group(1)) * mult.get((m.group(2) or "B").upper(), 1))

    def _parse_size_text(self, text: str) -> int:
        m = re.search(r"\b([\d.]+)\s*(TB|GB|MB|KB)\b", text.replace(",", "."), re.I)
        return self._parse_size(m.group(0)) if m else 0

    def _nearby_size_bytes(self, html: str, raw_url: Any) -> int:
        needle = str(raw_url)
        idx = html.find(needle)
        if idx < 0:
            return 0
        return self._parse_size_text(html[max(0, idx - 500): idx + 500])

    def _extract_tags(self, html: str) -> List[str]:
        tags = self._meta(html, "keywords")
        if tags:
            return [t.strip() for t in tags.split(",") if t.strip()]
        return []

    def _extract_uploader(self, html: str) -> str:
        for pattern in (
            r'(?:model|uploader|performer|author)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'class=["\'][^"\']*(?:model|uploader|performer|author)[^"\']*["\'][^>]*>([^<]+)<',
        ):
            m = re.search(pattern, html, re.I)
            if m:
                return re.sub(r"\s+", " ", unescape(m.group(1))).strip()
        return ""

    def _first_url(self, value: Any) -> str:
        if isinstance(value, list):
            return self._first_url(value[0]) if value else ""
        if isinstance(value, dict):
            return str(value.get("url") or "")
        return str(value or "")

    def _int(self, value: Any) -> int:
        try:
            return int(float(value))
        except Exception:
            return 0

    def _id_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        return parts[-1] if parts else parsed.netloc
