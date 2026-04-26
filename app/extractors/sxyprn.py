"""
SxyPrn extractor.

SxyPrn (sxyprn.com) is an aggregator — it embeds videos from various
third-party hosts (DoodStream, LuluStream, BigWarp, Filemoon, Vidara,
Gofile, Bunkr, Pixeldrain, …).

This extractor:
  1. Fetches the SxyPrn page.
  2. Detects which host is being used (iframe src / <a> links / JS vars).
  3. Delegates to the matching registered extractor.
  4. Enriches the result with the SxyPrn page title / tags if available.
"""

import logging
import re
from typing import Optional, Dict, Any

import httpx
from bs4 import BeautifulSoup

from .base import VideoExtractor
from .registry import ExtractorRegistry

logger = logging.getLogger(__name__)

# All media hosts we know how to handle (used for link/iframe detection).
# Keep this list in sync with the extractors registered in __init__.py.
_KNOWN_HOSTS = [
    # LuluStream
    "lulustream.com", "luluvdo.com", "lulustream.net",
    # DoodStream
    "doodstream.com", "dood.watch", "dood.so", "dood.cx", "dood.la",
    "dood.li", "dood.re", "dood.pm", "dood.to", "dood.stream",
    "dooood.com", "dood.yt", "d0000d.com", "ds2video.com", "do0od.com",
    "dood.ws", "doodwatch.com",
    # BigWarp
    "bigwarp.io", "bigwarp.tv",
    # Filemoon
    "filemoon.sx", "filemoon.in", "filemoon.to", "moonplayer.one",
    "filemoonapi.com", "kerapoxy.cc", "alions.pro", "smashystream.xyz",
    # Vidara
    "vidara.so", "vidara.xyz",
    # Gofile
    "gofile.io",
    # Bunkr
    "bunkr.si", "bunkr.ru", "bunkr.black", "bunkr.media",
    "bunkrr.su", "bunkr.su", "bunkr.pk",
    # Pixeldrain
    "pixeldrain.com",
    # StreamSB / StreamTape / Mixdrop (common on NSFW aggr. sites)
    "streamsb.net", "sbplay.org", "sbembed.com",
    "streamtape.com", "streamtape.net", "streamtape.to",
    "mixdrop.co", "mixdrop.to", "mixdrop.bz",
    # Streamlare
    "streamlare.com",
    # Upstream
    "upstream.to",
]


class SxyPrnExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "SxyPrn"

    def can_handle(self, url: str) -> bool:
        return "sxyprn.com" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetches the SxyPrn page and delegates to the appropriate host extractor.
        """
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Referer": "https://sxyprn.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=True, headers=headers
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(
                        "[SxyPrn] page returned %s for %s", resp.status_code, url
                    )
                    return None
                html = resp.text

            soup = BeautifulSoup(html, "html.parser")

            # ── Page metadata ─────────────────────────────────────────────
            sxy_title = self._extract_title(soup, html)
            sxy_tags  = self._extract_tags(soup)

            # ── Find the embedded media URL ───────────────────────────────
            media_url = (
                self._find_in_iframes(soup)
                or self._find_in_links(soup)
                or self._find_in_scripts(html)
            )

            if not media_url:
                logger.warning("[SxyPrn] no supported host link found in %s", url)
                return None

            logger.info("[SxyPrn] found media URL: %s", media_url)

            # ── Delegate to matching extractor ────────────────────────────
            extractor = ExtractorRegistry.find_extractor(media_url)
            if not extractor or extractor is self:
                logger.warning(
                    "[SxyPrn] no extractor available for %s", media_url
                )
                return None

            logger.info("[SxyPrn] delegating to %s", extractor.name)
            result = await extractor.extract(media_url)

            if result:
                # Enrich with SxyPrn page metadata
                if sxy_title:
                    result["title"] = sxy_title
                if sxy_tags:
                    existing = result.get("tags") or []
                    if isinstance(existing, str):
                        existing = [t.strip() for t in existing.split(",") if t.strip()]
                    result["tags"] = list(dict.fromkeys(sxy_tags + existing))
                result["source_url"] = url

            return result

        except Exception as exc:
            logger.error("[SxyPrn] extraction failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------ #
    #  Detection helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_in_iframes(soup: BeautifulSoup) -> Optional[str]:
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src") or iframe.get("data-src") or ""
            src = src.strip()
            if src and any(h in src for h in _KNOWN_HOSTS):
                return src
        return None

    @staticmethod
    def _find_in_links(soup: BeautifulSoup) -> Optional[str]:
        for a in soup.find_all("a", href=True):
            href = (a["href"] or "").strip()
            if href and any(h in href for h in _KNOWN_HOSTS):
                return href
        return None

    @staticmethod
    def _find_in_scripts(html: str) -> Optional[str]:
        """
        Scan <script> blocks for embed URLs or variable assignments.
        Handles patterns like:
          file: "https://lulustream.com/e/ABC"
          src = "https://dood.watch/e/XYZ"
          iframe.src = "..."
        """
        patterns = [
            r"""(?:file|src|url|embed)\s*[:=]\s*["']([^"']+)["']""",
            r"""["'](https?://(?:{hosts})[^"']+)["']""".format(
                hosts="|".join(re.escape(h) for h in _KNOWN_HOSTS)
            ),
        ]
        for pat in patterns:
            for m in re.finditer(pat, html, re.I):
                candidate = m.group(1).strip()
                if any(h in candidate for h in _KNOWN_HOSTS):
                    return candidate
        return None

    # ------------------------------------------------------------------ #
    #  Metadata helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_title(soup: BeautifulSoup, html: str) -> str:
        # og:title first
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        # <title> tag
        title_tag = soup.find("title")
        if title_tag:
            t = title_tag.get_text().strip()
            # Strip site suffix
            t = re.sub(r"\s*[-|]\s*SxyPrn.*$", "", t, flags=re.I)
            if t:
                return t
        # h1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text().strip()
        return ""

    @staticmethod
    def _extract_tags(soup: BeautifulSoup) -> list:
        tags = []
        # <a class="tag ...">
        for a in soup.find_all("a", class_=re.compile(r"tag", re.I)):
            text = a.get_text().strip()
            if text and len(text) < 50:
                tags.append(text.lower())
        # meta keywords
        kw_meta = soup.find("meta", attrs={"name": "keywords"})
        if kw_meta and kw_meta.get("content"):
            for kw in kw_meta["content"].split(","):
                kw = kw.strip().lower()
                if kw and kw not in tags:
                    tags.append(kw)
        return tags[:30]  # cap at 30
