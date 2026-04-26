"""
Filemoon extractor.

Filemoon (filemoon.sx / filemoon.in / moonplayer.one / etc.) uses a
packed/obfuscated JS (p,a,c,k,e,d) pattern to embed the m3u8 URL.

Extraction flow:
  1. Fetch the embed page (/e/{filecode} or /v/{filecode}).
  2. Find the p,a,c,k,e,d JS block and eval-decode it in Python.
  3. Pull the m3u8 URL out of the decoded JS (sources:[{file:"..."}]).
"""

import logging
import re
from typing import Optional, Dict, Any

import httpx
from .base import VideoExtractor

logger = logging.getLogger(__name__)

_FILEMOON_DOMAINS = (
    "filemoon.sx",
    "filemoon.in",
    "filemoon.to",
    "moonplayer.one",
    "filemoonapi.com",
    "kerapoxy.cc",
    "alions.pro",
    "moviesm4u.cc",
    "acefile.co",
    "smashystream.xyz",
)


def _unpack(packed: str) -> str:
    """
    Pure-Python implementation of Dean Edwards' p,a,c,k,e,d unpacker.
    Works on the 'eval(function(p,a,c,k,e,d){...}(...)' pattern.
    """
    # Extract the payload arguments from the outer eval call
    m = re.search(
        r"""eval\s*\(\s*function\s*\(p,a,c,k,e,[d|_]\)\s*\{.*?\}\s*\((.+)\)\s*\)""",
        packed,
        re.DOTALL,
    )
    if not m:
        return packed

    args_str = m.group(1)

    # Split the args string carefully (last 4 args after the first big string)
    # Pattern: 'encoded_str',base,count,'word|word|...',...
    try:
        # Find the string argument (first quoted string), base, count, and dict
        str_match   = re.match(r"""(['"])(.+?)\1""", args_str, re.DOTALL)
        if not str_match:
            return packed
        encoded = str_match.group(2)

        rest = args_str[str_match.end():].lstrip(", ")
        nums = re.findall(r'\d+', rest[:40])
        if len(nums) < 2:
            return packed

        radix = int(nums[0])   # base
        count = int(nums[1])   # number of symbols

        # Find the keyword list (pipe-separated inside quotes)
        dict_match = re.search(r"""(['"])([^'"]*)\1""", rest)
        if not dict_match:
            return packed

        keywords = dict_match.group(2).split("|")

        def _base_decode(s: str, base: int) -> int:
            digits = "0123456789abcdefghijklmnopqrstuvwxyz"
            result = 0
            for c in s.lower():
                result = result * base + digits.index(c)
            return result

        def _replace(match):
            word = match.group(0)
            idx  = _base_decode(word, radix)
            return keywords[idx] if idx < len(keywords) and keywords[idx] else word

        # Words are base-radix numbers in the encoded string
        return re.sub(r'\b\w+\b', _replace, encoded)

    except Exception as exc:
        logger.debug("[Filemoon] unpack error: %s", exc)
        return packed


class FilemoonExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Filemoon"

    def can_handle(self, url: str) -> bool:
        return any(d in url for d in _FILEMOON_DOMAINS)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        filecode = self._filecode(url)
        if not filecode:
            logger.warning("[Filemoon] cannot extract filecode from %s", url)
            return None

        # Try known domain variants for embed
        host = next((d for d in _FILEMOON_DOMAINS if d in url), "filemoon.sx")
        embed_url = f"https://{host}/e/{filecode}"

        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Referer": embed_url,
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=True, headers=headers
            ) as client:
                resp = await client.get(embed_url)
                if resp.status_code != 200:
                    logger.warning(
                        "[Filemoon] embed returned %s for %s", resp.status_code, embed_url
                    )
                    return None

                html = resp.text

            stream_url = self._extract_stream(html)
            if not stream_url:
                logger.warning("[Filemoon] could not extract stream from %s", embed_url)
                return None

            title     = self._extract_meta(html, "og:title") or f"Filemoon {filecode}"
            thumbnail = self._extract_meta(html, "og:image") or ""
            duration  = self._extract_duration(html)

            return {
                "id":          filecode,
                "title":       title,
                "description": "",
                "thumbnail":   thumbnail,
                "duration":    duration,
                "stream_url":  stream_url,
                "width":       0,
                "height":      0,
                "tags":        ["filemoon"],
                "uploader":    "Filemoon",
                "is_hls":      ".m3u8" in stream_url.lower(),
                "referer":     embed_url,
            }

        except Exception as exc:
            logger.error("[Filemoon] extraction failed for %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _filecode(url: str) -> Optional[str]:
        m = re.search(r"/(?:e|v|embed|d)/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
        # bare filecode: filemoon.sx/AbCdEfGh
        m = re.search(r"filemoon\.\w+/([A-Za-z0-9]{8,})", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_stream(html: str) -> Optional[str]:
        """Decode the packed JS and pull out the m3u8 source URL."""
        # 1. Try decoding packed JS blocks
        for packed_block in re.findall(
            r'(eval\s*\(function\s*\(p,a,c,k,e,[\w_]\).*?\}\s*\([^)]+\)\s*\))',
            html,
            re.DOTALL,
        ):
            decoded = _unpack(packed_block)
            m = re.search(r"""["']file["']\s*:\s*["']([^"']+\.m3u8[^"']*)["']""", decoded)
            if m:
                return m.group(1)
            m = re.search(r"""["']src["']\s*:\s*["']([^"']+\.m3u8[^"']*)["']""", decoded)
            if m:
                return m.group(1)

        # 2. Direct m3u8 in page (unobfuscated)
        m = re.search(r"""["'](https?://[^"']+\.m3u8[^"']*)["']""", html)
        if m:
            return m.group(1)

        # 3. sources JSON array
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
        m = re.search(
            rf'content=["\']([^"\']+)["\'][^>]*property=["\']{{prop}}["\']'.replace("{prop}", prop),
            html, re.I,
        )
        if m:
            return m.group(1).strip()
        return ""

    @staticmethod
    def _extract_duration(html: str) -> int:
        m = re.search(r'"duration"\s*:\s*"?(\d+)"?', html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return 0
