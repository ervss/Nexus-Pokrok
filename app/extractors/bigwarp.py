"""
BigWarp extractor.

BigWarp (bigwarp.io) is a video hosting site that uses HLS streaming.
It serves its player page as an iframe embed:
  https://bigwarp.io/e/{filecode}

Extraction strategy:
  1. Try yt-dlp first (works on bigwarp.io as of 2024).
  2. If yt-dlp fails, scrape the embed page for jwplayer/videojs config
     or direct m3u8 links.
"""

import logging
import re
from typing import Optional, Dict, Any

import httpx
from .base import VideoExtractor

logger = logging.getLogger(__name__)

_BIGWARP_DOMAINS = (
    "bigwarp.io",
    "bigwarp.tv",
)


class BigWarpExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "BigWarp"

    def can_handle(self, url: str) -> bool:
        return any(d in url for d in _BIGWARP_DOMAINS)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # 1. Try yt-dlp (import is lazy so it doesn't crash if missing)
        result = self._try_ytdlp(url)
        if result:
            return result

        # 2. Fallback: scrape embed page
        result = await self._scrape(url)
        return result

    # ------------------------------------------------------------------ #
    #  yt-dlp path                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _try_ytdlp(url: str) -> Optional[Dict[str, Any]]:
        try:
            import yt_dlp  # type: ignore

            opts = {
                "quiet": True,
                "skip_download": True,
                "format": "best[ext=mp4]/best",
                "socket_timeout": 15,
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}

            stream_url = info.get("url") or ""
            if not stream_url and info.get("formats"):
                fmts = sorted(
                    [f for f in info["formats"] if f.get("url")],
                    key=lambda f: (f.get("height") or 0),
                    reverse=True,
                )
                if fmts:
                    stream_url = fmts[0]["url"]

            if not stream_url:
                return None

            h = int(info.get("height") or 0)
            return {
                "id":          info.get("id", ""),
                "title":       info.get("title", "BigWarp Video"),
                "description": info.get("description", ""),
                "thumbnail":   info.get("thumbnail", ""),
                "duration":    int(info.get("duration") or 0),
                "stream_url":  stream_url,
                "width":       int(info.get("width") or 0),
                "height":      h,
                "tags":        ["bigwarp"],
                "uploader":    info.get("uploader", "BigWarp"),
                "is_hls":      ".m3u8" in stream_url.lower(),
            }

        except Exception as exc:
            logger.debug("[BigWarp] yt-dlp failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------ #
    #  Scrape fallback                                                     #
    # ------------------------------------------------------------------ #

    async def _scrape(self, url: str) -> Optional[Dict[str, Any]]:
        filecode = self._filecode(url)
        host     = next((d for d in _BIGWARP_DOMAINS if d in url), "bigwarp.io")
        embed_url = f"https://{host}/e/{filecode}" if filecode else url

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        try:
            async with httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": ua, "Referer": embed_url},
            ) as client:
                resp = await client.get(embed_url)
                if resp.status_code != 200:
                    logger.warning(
                        "[BigWarp] embed returned %s for %s", resp.status_code, embed_url
                    )
                    return None

                html = resp.text

            stream_url = self._find_stream(html)
            if not stream_url:
                logger.warning("[BigWarp] no stream found in %s", embed_url)
                return None

            title     = self._extract_meta(html, "og:title") or f"BigWarp {filecode or 'Video'}"
            thumbnail = self._extract_meta(html, "og:image") or ""

            return {
                "id":          filecode or "",
                "title":       title,
                "description": "",
                "thumbnail":   thumbnail,
                "duration":    0,
                "stream_url":  stream_url,
                "width":       0,
                "height":      0,
                "tags":        ["bigwarp"],
                "uploader":    "BigWarp",
                "is_hls":      ".m3u8" in stream_url.lower(),
                "referer":     embed_url,
            }

        except Exception as exc:
            logger.error("[BigWarp] scrape failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _filecode(url: str) -> Optional[str]:
        m = re.search(r"/(?:e|v|embed)/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"bigwarp\.\w+/([A-Za-z0-9]{6,})", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _find_stream(html: str) -> Optional[str]:
        # m3u8 direct
        m = re.search(r"""["'](https?://[^"']+\.m3u8[^"']*)["']""", html)
        if m:
            return m.group(1)
        # mp4 direct
        m = re.search(r"""["'](https?://[^"']+\.mp4[^"']*)["']""", html)
        if m:
            return m.group(1)
        # JW Player sources
        m = re.search(
            r"""sources\s*:\s*\[\s*\{[^}]*["']file["']\s*:\s*["']([^"']+)["']""",
            html, re.DOTALL,
        )
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_meta(html: str, prop: str) -> str:
        m = re.search(
            rf'property=["\']{{prop}}["\'][^>]*content=["\']([^"\']+)["\']'.replace("{prop}", prop),
            html, re.I,
        )
        if m:
            return m.group(1).strip()
        return ""
