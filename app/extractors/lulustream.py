"""
LuluStream extractor.

LuluStream serves videos via a POST API:
  POST https://lulustream.com/api/source/{filecode}
  Body: r=<referer>&d=lulustream.com

The response JSON has the shape:
  { "success": true, "data": [{"file": "https://...m3u8", "type": "video/mp4", "label": "..."}], ... }

Embed URLs look like:
  https://lulustream.com/e/{filecode}
  https://lulustream.com/{filecode}
"""

import logging
import re
import asyncio
from typing import Optional, Dict, Any

import httpx
from .base import VideoExtractor

logger = logging.getLogger(__name__)

_LULU_DOMAINS = ("lulustream.com", "luluvdo.com", "lulustream.net")


class LuluStreamExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "LuluStream"

    def can_handle(self, url: str) -> bool:
        return any(d in url for d in _LULU_DOMAINS)

    # ------------------------------------------------------------------ #
    #  Public entry-point                                                  #
    # ------------------------------------------------------------------ #

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        filecode = self._filecode(url)
        if not filecode:
            logger.warning("[LuluStream] cannot extract filecode from %s", url)
            return None

        # Normalize to embed URL
        embed_url = f"https://lulustream.com/e/{filecode}"
        domain    = "lulustream.com"

        headers_base = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": embed_url,
            "Origin":  f"https://{domain}",
        }

        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers=headers_base,
            ) as client:
                # 1. Fetch embed page to grab cookies / any page metadata
                page_resp = await client.get(embed_url)
                title, thumbnail, duration = self._parse_embed_page(page_resp.text, filecode)

                # 2. Call /api/source/
                api_url = f"https://{domain}/api/source/{filecode}"
                api_resp = await client.post(
                    api_url,
                    data={"r": embed_url, "d": domain},
                    headers={
                        **headers_base,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )

                if api_resp.status_code != 200:
                    logger.warning(
                        "[LuluStream] API returned %s for %s",
                        api_resp.status_code, filecode,
                    )
                    return None

                data = api_resp.json()
                if not data.get("success"):
                    logger.warning(
                        "[LuluStream] API not successful for %s: %s",
                        filecode, data.get("error", "unknown"),
                    )
                    return None

                sources = data.get("data", [])
                if not sources:
                    logger.warning("[LuluStream] empty sources for %s", filecode)
                    return None

                # Pick highest quality source
                stream_url = self._best_source(sources)
                if not stream_url:
                    return None

                is_hls = ".m3u8" in stream_url.lower()
                height = self._height_from_sources(sources)

                return {
                    "id":          filecode,
                    "title":       title or f"LuluStream {filecode}",
                    "description": "",
                    "thumbnail":   thumbnail or "",
                    "duration":    int(duration) if duration else 0,
                    "stream_url":  stream_url,
                    "width":       0,
                    "height":      height,
                    "tags":        ["lulustream"],
                    "uploader":    "LuluStream",
                    "is_hls":      is_hls,
                }

        except Exception as exc:
            logger.error("[LuluStream] extraction failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _filecode(url: str) -> Optional[str]:
        """Extract the filecode from any lulustream URL."""
        m = re.search(r"/(?:e|v|embed)/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
        # Bare filecode at end: lulustream.com/AbCdEf123
        m = re.search(r"lulustream\.com/([A-Za-z0-9]{8,})", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _parse_embed_page(html: str, filecode: str):
        """Pull title, thumbnail, duration from the embed page HTML."""
        title = thumbnail = ""
        duration = 0

        m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        if m:
            title = m.group(1).strip()

        m = re.search(r'og:image["\s]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            thumbnail = m.group(1).strip()

        m = re.search(r'"duration"\s*:\s*"?(\d+)"?', html)
        if m:
            try:
                duration = int(m.group(1))
            except ValueError:
                pass

        return title, thumbnail, duration

    @staticmethod
    def _best_source(sources: list) -> Optional[str]:
        """Return the URL of the highest-quality source."""
        if not sources:
            return None

        def _res_key(s):
            lbl = str(s.get("label", "")).lower()
            for p in ("2160", "4k", "1440", "1080", "720", "480", "360"):
                if p in lbl:
                    return int(p.replace("4k", "2160"))
            return 0

        sources_sorted = sorted(sources, key=_res_key, reverse=True)
        return sources_sorted[0].get("file") or None

    @staticmethod
    def _height_from_sources(sources: list) -> int:
        for s in sources:
            lbl = str(s.get("label", "")).lower()
            m = re.search(r"(\d{3,4})", lbl)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return 0
