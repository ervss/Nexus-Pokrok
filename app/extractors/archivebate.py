import asyncio
import json
import logging
import re
from html import unescape
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp

from .base import VideoExtractor

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ArchivebateExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Archivebate"

    def can_handle(self, url: str) -> bool:
        return "archivebate.com" in (url or "").lower()

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._extract_sync, url)

    def _extract_sync(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            page_url = self._normalize_url(url)
            headers = self._headers("https://www.archivebate.com/")

            if self._is_direct_media(page_url):
                return self._result(page_url, page_url, stream_url=page_url)

            html = self._get_text(page_url, headers)
            if not html:
                return self._try_ytdlp(page_url)

            metadata = self._extract_metadata(html, page_url)
            stream_url = self._extract_direct_stream(html, page_url)

            embed_url = self._extract_embed_url(html, page_url)
            if embed_url and not stream_url:
                if "archivebate.com/embed/" in embed_url.lower():
                    embed_html = self._get_text(embed_url, self._headers(page_url))
                    if embed_html:
                        stream_url = self._extract_direct_stream(embed_html, embed_url)
                        metadata = {**self._extract_metadata(embed_html, embed_url), **metadata}
                elif "mixdrop." in embed_url.lower() or "m1xdrop." in embed_url.lower():
                    stream_url = self._resolve_mixdrop_stream(embed_url, referer=page_url)

            # Avoid noisy unsupported-provider errors from yt-dlp for Archivebate/Mixdrop.
            # Keep a deterministic fallback to embed URL if direct stream is not derivable.

            if not stream_url and embed_url:
                # Keep provider/embed URLs refreshable instead of failing the import completely.
                stream_url = embed_url

            if not stream_url:
                logger.warning("[Archivebate] no stream found for %s", page_url)
                return None

            return self._result(
                page_url,
                page_url,
                stream_url=stream_url,
                title=metadata.get("title") or "Archivebate Video",
                thumbnail=metadata.get("thumbnail") or "",
                duration=metadata.get("duration") or 0,
                height=metadata.get("height") or self._guess_height(metadata.get("title", "") + html[:2000]),
                tags=metadata.get("tags") or [],
            )
        except Exception as e:
            logger.error("[Archivebate] extract failed for %s: %s", url, e, exc_info=True)
            return None

    def _normalize_url(self, url: str) -> str:
        if not url:
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return urljoin("https://www.archivebate.com/", url)
        return url

    def _headers(self, referer: str) -> Dict[str, str]:
        return {
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _get_text(self, url: str, headers: Dict[str, str]) -> str:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning("[Archivebate] HTTP %s for %s", resp.status_code, url)
            return ""
        return resp.text

    def _extract_metadata(self, html: str, page_url: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"title": "", "thumbnail": "", "duration": 0, "tags": []}

        for match in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.I | re.S,
        ):
            try:
                data = json.loads(match.strip())
                if isinstance(data, list):
                    data = next((x for x in data if isinstance(x, dict)), {})
                if isinstance(data, dict):
                    out["title"] = data.get("name") or out["title"]
                    thumb = data.get("thumbnailUrl") or data.get("thumbnail")
                    if isinstance(thumb, list):
                        thumb = thumb[0] if thumb else ""
                    if isinstance(thumb, dict):
                        thumb = thumb.get("url")
                    out["thumbnail"] = thumb or out["thumbnail"]
                    out["duration"] = self._parse_iso_duration(data.get("duration")) or out["duration"]
                    keywords = data.get("keywords")
                    if isinstance(keywords, str):
                        out["tags"] = [t.strip() for t in keywords.split(",") if t.strip()]
            except Exception:
                continue

        out["title"] = out["title"] or self._meta(html, "og:title") or self._title_tag(html) or "Archivebate Video"
        out["thumbnail"] = self._normalize_media_url(out["thumbnail"] or self._meta(html, "og:image"), page_url)
        if not out["duration"]:
            out["duration"] = self._parse_duration_text(html)
        out["height"] = self._guess_height(out["title"] + " " + html[:2000])
        return out

    def _extract_embed_url(self, html: str, page_url: str) -> str:
        patterns = [
            r'<iframe[^>]+src=["\']([^"\']+)["\']',
            r'(https?://(?:www\.)?archivebate\.com/embed/[^"\'<>\s]+)',
            r'(https?://(?:www\.)?mixdrop\.[^"\'<>\s]+/[^"\'<>\s]+)',
        ]
        for pattern in patterns:
            for raw in re.findall(pattern, html, re.I):
                candidate = self._normalize_url(unescape(raw))
                if not candidate.startswith("http"):
                    candidate = urljoin(page_url, candidate)
                if any(host in candidate.lower() for host in ["archivebate.com/embed", "mixdrop.", "dood", "filemoon", "voe.", "streamtape", "lulu"]):
                    return candidate
        return ""

    def _extract_direct_stream(self, html: str, page_url: str) -> str:
        patterns = [
            r'["\'](https?://[^"\']+?\.m3u8(?:\?[^"\']*)?)["\']',
            r'["\'](https?://[^"\']+?\.mp4(?:\?[^"\']*)?)["\']',
            r'["\'](//[^"\']+?\.m3u8(?:\?[^"\']*)?)["\']',
            r'["\'](//[^"\']+?\.mp4(?:\?[^"\']*)?)["\']',
            r'(https?://[^"\'<>\s]+video-delivery\.net[^"\'<>\s]+)',
            r'file\s*:\s*["\']([^"\']+)["\']',
            r'src\s*:\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
            r'<source[^>]+src=["\']([^"\']+)["\']',
            r'<video[^>]+src=["\']([^"\']+)["\']',
        ]
        for pattern in patterns:
            for raw in re.findall(pattern, html, re.I):
                candidate = self._normalize_media_url(unescape(raw).replace("\\/", "/"), page_url)
                if self._is_usable_stream(candidate):
                    return candidate
        return ""

    def _resolve_mixdrop_stream(self, embed_url: str, referer: str = "") -> str:
        try:
            html = self._get_text(embed_url, self._headers(referer or "https://archivebate.com/"))
            if not html:
                return ""

            # Sometimes direct URLs are already present.
            direct = self._extract_direct_stream(html, embed_url)
            if direct:
                return direct

            unpacked = self._unpack_packer(html)
            if not unpacked:
                return ""

            direct = self._extract_direct_stream(unpacked, embed_url)
            if direct:
                return direct
        except Exception as e:
            logger.debug("[Archivebate] mixdrop resolve failed for %s: %s", embed_url, e)
        return ""

    def _unpack_packer(self, html: str) -> str:
        """
        Unpack common eval(function(p,a,c,k,e,d){...}) payload used by Mixdrop.
        Returns unpacked script source, or empty string on failure.
        """
        m = re.search(
            r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\(\s*'(?P<p>.*?)'\s*,\s*(?P<a>\d+)\s*,\s*(?P<c>\d+)\s*,\s*'(?P<k>.*?)'\.split\('\|'\)",
            html,
            re.S,
        )
        if not m:
            return ""

        payload = m.group("p")
        base = int(m.group("a"))
        count = int(m.group("c"))
        keys = m.group("k").split("|")

        def _to_base(num: int, b: int) -> str:
            chars = "0123456789abcdefghijklmnopqrstuvwxyz"
            if num == 0:
                return "0"
            out = []
            n = num
            while n > 0:
                n, rem = divmod(n, b)
                out.append(chars[rem])
            return "".join(reversed(out))

        unpacked = payload
        for i in range(count - 1, -1, -1):
            if i >= len(keys):
                continue
            replacement = keys[i]
            if not replacement:
                continue
            token = _to_base(i, base)
            unpacked = re.sub(rf"\b{re.escape(token)}\b", replacement, unpacked)

        # De-escape minimal sequences commonly present in packed strings.
        unpacked = unpacked.replace("\\/", "/")
        return unpacked

    def _try_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "format": "best[protocol*=m3u8]/best[ext=mp4]/best",
                "http_headers": self._headers("https://www.archivebate.com/"),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                return None
            stream_url = info.get("url")
            if not stream_url and info.get("formats"):
                fmts = [f for f in info["formats"] if f.get("url")]
                fmts.sort(key=lambda f: f.get("height") or 0, reverse=True)
                if fmts:
                    stream_url = fmts[0]["url"]
            if not stream_url:
                return None
            return self._result(
                url,
                url,
                stream_url=stream_url,
                title=info.get("title") or "Archivebate Video",
                thumbnail=info.get("thumbnail") or "",
                duration=float(info.get("duration") or 0),
                height=int(info.get("height") or 0),
                tags=info.get("tags") or [],
                size_bytes=info.get("filesize") or info.get("filesize_approx") or 0,
            )
        except Exception as e:
            logger.debug("[Archivebate] yt-dlp failed for %s: %s", url, e)
            return None

    def _result(self, page_url: str, source_url: str, **kwargs: Any) -> Dict[str, Any]:
        height = int(kwargs.get("height") or 0)
        return {
            "id": self._id_from_url(page_url),
            "title": kwargs.get("title") or "Archivebate Video",
            "description": "",
            "thumbnail": kwargs.get("thumbnail") or "",
            "duration": float(kwargs.get("duration") or 0),
            "stream_url": kwargs.get("stream_url") or page_url,
            "width": int(kwargs.get("width") or self._width_for_height(height)),
            "height": height,
            "size_bytes": int(kwargs.get("size_bytes") or 0),
            "tags": kwargs.get("tags") or [],
            "uploader": "Archivebate",
            "is_hls": ".m3u8" in (kwargs.get("stream_url") or "").lower(),
            "source_url": source_url,
        }

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
        path = urlparse(url).path.lower()
        return path.endswith((".mp4", ".m4v", ".mov", ".mkv", ".webm", ".m3u8"))

    def _is_usable_stream(self, url: str) -> bool:
        low = (url or "").lower()
        if not low.startswith("http"):
            return False
        if any(x in low for x in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js"]):
            return False
        return any(x in low for x in [".mp4", ".m3u8", "video-delivery.net"])

    def _meta(self, html: str, prop: str) -> str:
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        return unescape(m.group(1)).strip() if m else ""

    def _title_tag(self, html: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if not m:
            return ""
        return re.sub(r"\s+", " ", unescape(m.group(1))).replace("Archivebate", "").strip(" -|")

    def _parse_iso_duration(self, value: Any) -> float:
        if not value or not isinstance(value, str):
            return 0
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value, re.I)
        if not m:
            return 0
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)

    def _parse_duration_text(self, html: str) -> float:
        text = re.sub(r"<[^>]+>", " ", html[:5000])
        m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
        if not m:
            return 0
        if m.group(3):
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        return int(m.group(1)) * 60 + int(m.group(2))

    def _guess_height(self, text: str) -> int:
        m = re.search(r"\b(2160|1440|1080|720|480|360)p?\b", text or "", re.I)
        return int(m.group(1)) if m else 720

    def _width_for_height(self, height: int) -> int:
        return {2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640}.get(height, 0)

    def _id_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        return parts[-1] if parts else url
