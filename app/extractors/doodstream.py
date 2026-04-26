"""
DoodStream extractor.

DoodStream (dood.watch / doodstream.com / d0000d.com / dooood.com / etc.)
uses a two-step process:
  1. Fetch the video page (e.g. https://dood.watch/d/{filecode})
  2. Parse out the "pass_md5" path  from the JS block, e.g.:
       $.get('/pass_md5/abc...', function(data) { ... }
     and a token string like:
       token = 'xxxx'
  3. GET https://dood.watch/pass_md5/{pass_md5_path}?{random}&token={token}
     — the server responds with a CDN base URL (no extension).
  4. Append '?token={token}&expiry={epoch_ms}' to get the actual stream URL.

All known mirrors are handled via _DOOD_DOMAINS.
"""

import logging
import random
import re
import string
import time
from typing import Optional, Dict, Any

import httpx
from .base import VideoExtractor

logger = logging.getLogger(__name__)

_DOOD_DOMAINS = (
    "doodstream.com",
    "dood.watch",
    "dood.so",
    "dood.cx",
    "dood.la",
    "dood.li",
    "dood.re",
    "dood.pm",
    "dood.to",
    "dood.stream",
    "dooood.com",
    "dood.yt",
    "d0000d.com",
    "ds2video.com",
    "do0od.com",
    "dood.ws",
    "doodwatch.com",
)


def _random_str(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class DoodStreamExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "DoodStream"

    def can_handle(self, url: str) -> bool:
        return any(d in url for d in _DOOD_DOMAINS)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # Normalise to the most common domain in case redirects differ
        try:
            return await self._do_extract(url)
        except Exception as exc:
            logger.error("[DoodStream] extraction failed for %s: %s", url, exc)
            return None

    async def _do_extract(self, url: str) -> Optional[Dict[str, Any]]:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": ua, "Referer": url},
        ) as client:
            # ── Step 1: fetch the watch page ──────────────────────────────
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("[DoodStream] page returned %s for %s", resp.status_code, url)
                return None

            html = resp.text
            base_url = f"{resp.url.scheme}://{resp.url.host}"

            # ── Step 2: extract pass_md5 path and token ───────────────────
            pass_md5_match = re.search(
                r"""['"]/pass_md5/([^'"]+)['"]""",
                html,
            )
            if not pass_md5_match:
                logger.warning("[DoodStream] no pass_md5 found in %s", url)
                return None

            pass_md5_path = pass_md5_match.group(1)

            token_match = re.search(
                r"""[?&'"]token['"?\s]*[:=]+\s*['"]([A-Za-z0-9_-]{8,})['"]""",
                html,
            )
            if not token_match:
                # Fallback: token is last segment of pass_md5 path
                token = pass_md5_path.split("/")[-1]
            else:
                token = token_match.group(1)

            # ── Step 3: fetch the CDN base URL ────────────────────────────
            pass_url = f"{base_url}/pass_md5/{pass_md5_path}"
            headers_pass = {
                "User-Agent": ua,
                "Referer": url,
                "X-Requested-With": "XMLHttpRequest",
            }
            pass_resp = await client.get(
                pass_url,
                params={"token": token},
                headers=headers_pass,
            )
            if pass_resp.status_code != 200 or not pass_resp.text.strip():
                logger.warning(
                    "[DoodStream] pass_md5 returned %s for %s",
                    pass_resp.status_code, pass_url,
                )
                return None

            cdn_base = pass_resp.text.strip()

            # ── Step 4: assemble stream URL ───────────────────────────────
            expiry = int(time.time() * 1000)
            stream_url = f"{cdn_base}{_random_str(10)}?token={token}&expiry={expiry}"

            # ── Meta: title / thumbnail / duration ────────────────────────
            title = self._extract_title(html) or "DoodStream Video"
            thumbnail = self._extract_thumbnail(html) or ""
            duration = self._extract_duration(html)

            return {
                "id":          pass_md5_path.split("/")[-1],
                "title":       title,
                "description": "",
                "thumbnail":   thumbnail,
                "duration":    duration,
                "stream_url":  stream_url,
                "width":       0,
                "height":      0,
                "tags":        ["doodstream"],
                "uploader":    "DoodStream",
                "is_hls":      False,
                # DoodStream requires the Referer header to play
                "referer":     url,
            }

    # ------------------------------------------------------------------ #
    #  HTML parsing helpers                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_title(html: str) -> str:
        for pat in (
            r'<title[^>]*>([^<]+)</title>',
            r'og:title["\s]+content=["\']([^"\']+)["\']',
            r'"name"\s*:\s*"([^"]+)"',
        ):
            m = re.search(pat, html, re.I)
            if m:
                t = m.group(1).strip()
                # Strip site suffix
                t = re.sub(r'\s*[-|]\s*(DoodStream|Dood\.watch|Dood\.so).*$', '', t, flags=re.I)
                return t
        return ""

    @staticmethod
    def _extract_thumbnail(html: str) -> str:
        m = re.search(r'og:image["\s]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r'"thumbnail[Url]*"\s*:\s*"([^"]+)"', html, re.I)
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _extract_duration(html: str) -> int:
        for pat in (
            r'"duration"\s*:\s*"?(\d+)"?',
            r'video_duration\s*=\s*["\']?(\d+)',
        ):
            m = re.search(pat, html, re.I)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return 0
