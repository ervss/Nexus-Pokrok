"""
Smart media extraction router.

Architecture
============
Primary  → yt-dlp          (standard platforms: xvideos, xhamster, VK, spankbang, …)
Fallback → CyberDrop/KVS   (KVS-based sites: camwhores.tv, porntrex.com, …)
                            Uses curl_cffi for TLS-level browser impersonation that
                            bypasses Cloudflare, then decrypts the KVS obfuscated token
                            via cyberdrop_dl's internal `_parse_video_vars`.

Adding more extractors
----------------------
Subclass `BaseMediaExtractor`, override `can_handle()` and `extract()`, then
append your instance to the `_extractors` list in `build_default_router()`.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── Unified result ───────────────────────────────────────────────────────────

@dataclass
class MediaResult:
    """Unified output returned by every extractor."""
    stream_url: str
    source_url: str = ""
    title: str = ""
    thumbnail: str = ""
    duration: float = 0.0
    height: int = 0
    width: int = 0
    filesize: int = 0
    is_hls: bool = False
    extractor: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_url": self.stream_url,
            "source_url": self.source_url,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "height": self.height,
            "width": self.width,
            "filesize": self.filesize,
            "is_hls": self.is_hls,
            "extractor": self.extractor,
            **self.extra,
        }


# ─── Abstract base ────────────────────────────────────────────────────────────

class BaseMediaExtractor(ABC):
    name: str = "base"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this extractor knows how to process *url*."""

    @abstractmethod
    def extract(self, url: str, **kwargs) -> Optional[MediaResult]:
        """
        Synchronous extraction entry-point.
        Returns a MediaResult on success, None on failure.
        Implementations MUST NOT raise — swallow and return None instead.
        """


# ─── KVS / CyberDrop extractor ────────────────────────────────────────────────

# Sites that run the KernelVideoSharing (KVS) engine and are supported.
_KVS_DOMAINS = [
    "camwhores.tv",
    "porntrex.com",
    "ashemaletube.com",
    "dirtyship.com",
    "desivideo.com",
    "efukt.com",
]


def _height_from_resolution(res: Any) -> int:
    """Pull numeric height out of a cyberdrop_dl Resolution object (or int/None)."""
    try:
        if hasattr(res, "height"):
            return int(res.height or 0)
        return int(res or 0)
    except (TypeError, ValueError):
        return 0


def _width_for_height(h: int) -> int:
    mapping = {2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640}
    return mapping.get(h, 0)


class CyberDropKVSExtractor(BaseMediaExtractor):
    """
    Uses curl_cffi (TLS browser impersonation) to fetch the watch page,
    then delegates token decryption to cyberdrop_dl's `_parse_video_vars`.

    curl_cffi matches Chrome's TLS fingerprint at the socket level — this is
    the key difference vs plain requests / yt-dlp that Cloudflare can detect.
    """

    name = "cyberdrop_kvs"

    def can_handle(self, url: str) -> bool:
        u = (url or "").lower()
        return any(d in u for d in _KVS_DOMAINS)

    def extract(self, url: str, **kwargs) -> Optional[MediaResult]:
        try:
            from curl_cffi import requests as cffi_req
            from bs4 import BeautifulSoup
            from cyberdrop_dl.crawlers._kvs import Selectors as KvsSelectors, _parse_video_vars
            from cyberdrop_dl.utils import css as cdl_css

            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

            # Ensure URL has trailing slash (CW returns 404 without it)
            fetch_url = url.rstrip("/") + "/"

            logger.info("[KVS] fetching %s", fetch_url)
            resp = cffi_req.get(
                fetch_url,
                impersonate="chrome124",
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://" + (re.search(r"https?://([^/]+)", url) or [None, "www.camwhores.tv"])[1] + "/",
                },
                timeout=25,
            )

            if resp.status_code != 200:
                logger.warning("[KVS] HTTP %s for %s", resp.status_code, fetch_url)
                return None

            html = resp.text
            if not html or len(html) < 1000:
                logger.warning("[KVS] too short response for %s", fetch_url)
                return None

            soup = BeautifulSoup(html, "html.parser")

            # KVS flashvars: must use quoted text in :-soup-contains('…') — an unquoted
            # `video_id:` breaks soupsieve (':' starts a new pseudo-class). Same selector
            # as cyberdrop_dl Selectors.FLASHVARS.
            flashvars_tag = soup.select_one(KvsSelectors.FLASHVARS)
            if not flashvars_tag:
                logger.warning("[KVS] no flashvars block in %s", fetch_url)
                return None

            script_text = flashvars_tag.get_text()
            video = _parse_video_vars(script_text)

            stream_url = str(video.url)
            height = _height_from_resolution(video.resolution)
            width = _width_for_height(height)

            # Meta: title
            title = video.title or ""
            if not title:
                og = soup.select_one('meta[property="og:title"]')
                if og:
                    title = og.get("content", "").strip()

            # Meta: thumbnail
            thumbnail = ""
            og_img = soup.select_one('meta[property="og:image"]')
            if og_img:
                thumbnail = og_img.get("content", "").strip()

            # Meta: duration (seconds)
            duration = 0.0
            og_dur = soup.select_one('meta[property="video:duration"]')
            if og_dur:
                try:
                    duration = float(og_dur.get("content", 0))
                except (TypeError, ValueError):
                    pass
            if not duration:
                for pat in (
                    r'"duration"\s*:\s*"?(\d{2,6})"?',
                    r"video_duration['\"]?\s*[:=]\s*['\"]?(\d+)",
                    r'"duration"\s*:\s*"(PT[^"]+)"',
                ):
                    m = re.search(pat, html, re.I)
                    if m:
                        raw = m.group(1)
                        if raw.startswith("PT"):
                            pm = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw, re.I)
                            if pm:
                                try:
                                    duration = float(
                                        int(pm.group(1) or 0) * 3600
                                        + int(pm.group(2) or 0) * 60
                                        + int(pm.group(3) or 0)
                                    )
                                except ValueError:
                                    pass
                        else:
                            try:
                                v = float(raw)
                                if 10 <= v <= 21600:
                                    duration = v
                            except ValueError:
                                pass
                        if duration:
                            break

            logger.info(
                "[KVS] extracted url=%s h=%s dur=%.1f",
                stream_url[:80], height, duration,
            )
            return MediaResult(
                stream_url=stream_url,
                source_url=url,
                title=title,
                thumbnail=thumbnail,
                duration=duration,
                height=height,
                width=width,
                extractor=self.name,
            )

        except Exception as exc:
            logger.warning("[KVS] extract failed for %s: %s", url, exc, exc_info=True)
            return None


# ─── yt-dlp extractor ─────────────────────────────────────────────────────────

# Sites that should always go through yt-dlp (opt-in list).
# Everything else also falls through to yt-dlp as last resort.
_YTDLP_PREFERRED = [
    "xvideos.com", "xhamster.com", "spankbang.com",
    "vk.com", "vk.video", "vkvideo.ru",
    "eporner.com", "pornhub.com", "redtube.com",
    "xnxx.com", "tube8.com",
]


class YtDlpExtractor(BaseMediaExtractor):
    """yt-dlp based extractor — handles most mainstream platforms."""

    name = "yt_dlp"

    def can_handle(self, url: str) -> bool:
        # Accept everything (acts as catch-all fallback).
        return True

    def extract(self, url: str, cookie_file: Optional[str] = None, **kwargs) -> Optional[MediaResult]:
        try:
            import yt_dlp  # type: ignore

            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            opts: Dict[str, Any] = {
                "quiet": True,
                "skip_download": True,
                "format": "best[protocol*=m3u8]/best[ext=mp4]/best",
                "extract_flat": False,
                "socket_timeout": 20,
                "user_agent": ua,
                "http_headers": {"User-Agent": ua, "Referer": url},
            }
            if cookie_file:
                opts["cookiefile"] = cookie_file

            logger.info("[yt-dlp] extracting %s", url)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}

            stream_url = info.get("url", "")
            if not stream_url and info.get("formats"):
                # Pick best mp4 by height
                fmts = [f for f in info["formats"] if f.get("url")]
                if fmts:
                    fmts.sort(key=lambda f: (f.get("height") or 0), reverse=True)
                    stream_url = fmts[0]["url"]

            if not stream_url:
                logger.warning("[yt-dlp] no url extracted from %s", url)
                return None

            h = int(info.get("height") or 0)
            return MediaResult(
                stream_url=stream_url,
                source_url=url,
                title=info.get("title", ""),
                thumbnail=info.get("thumbnail", ""),
                duration=float(info.get("duration") or 0),
                height=h,
                width=int(info.get("width") or _width_for_height(h)),
                extractor=self.name,
            )

        except Exception as exc:
            logger.warning("[yt-dlp] extract failed for %s: %s", url, exc)
            return None


# ─── Router ───────────────────────────────────────────────────────────────────

class MediaExtractorRouter:
    """
    Tries each registered extractor in order.
    The first successful result is returned; others are tried only on failure.

    Usage
    -----
    router = build_default_router()
    result = router.extract("https://www.camwhores.tv/videos/...")
    if result:
        print(result.stream_url, result.height)
    """

    def __init__(self, extractors: Optional[List[BaseMediaExtractor]] = None) -> None:
        self._extractors: List[BaseMediaExtractor] = list(extractors or [])

    def register(self, extractor: BaseMediaExtractor, *, prepend: bool = False) -> "MediaExtractorRouter":
        """Add an extractor. Use *prepend=True* to give it highest priority."""
        if prepend:
            self._extractors.insert(0, extractor)
        else:
            self._extractors.append(extractor)
        return self

    def extract(self, url: str, **kwargs) -> Optional[MediaResult]:
        """Try each extractor in priority order, return first success."""
        for extractor in self._extractors:
            if not extractor.can_handle(url):
                continue
            logger.debug("[Router] trying %s for %s", extractor.name, url[:80])
            try:
                result = extractor.extract(url, **kwargs)
            except Exception as exc:
                logger.warning("[Router] %s raised unexpectedly: %s", extractor.name, exc)
                result = None
            if result and result.stream_url:
                logger.info("[Router] %s succeeded for %s", extractor.name, url[:80])
                return result
            logger.debug("[Router] %s returned nothing, trying next", extractor.name)
        logger.warning("[Router] all extractors failed for %s", url[:80])
        return None


# ─── Default singleton router ─────────────────────────────────────────────────

def build_default_router() -> MediaExtractorRouter:
    """
    Build the default routing chain:

        1. CyberDropKVSExtractor  — CamWhores, Porntrex, etc.  (curl_cffi + KVS decrypt)
        2. YtDlpExtractor         — everything else            (catch-all fallback)

    Extending: call router.register(MyExtractor(), prepend=True) to insert at the top.
    """
    router = MediaExtractorRouter()
    router.register(CyberDropKVSExtractor())
    router.register(YtDlpExtractor())
    return router


# Module-level default instance — import and use directly.
default_router = build_default_router()
