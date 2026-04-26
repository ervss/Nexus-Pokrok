"""
ixxx.com extractor: listings (search / categories) and watch-page stream resolution.

Fetch order: curl_cffi (TLS impersonation) -> Playwright -> optional FlareSolverr.
Listing calls avoid resolving stream_url; full extraction runs in extract() only.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from bs4 import BeautifulSoup

from .base import VideoExtractor

logger = logging.getLogger(__name__)

# Hosts we treat as ixxx frontends
_IXXX_HOST_SUFFIXES = ("ixxx.com",)

# Video detail paths seen on Tubetraffic-style tubes
_VIDEO_PATH_HINTS = re.compile(
    r"/(?:[a-z]{2}/)?(?:videos?|movie|out)(?:/|\?|$)",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


class IxxxExtractor(VideoExtractor):
    """
    Site-specific extractor for www.ixxx.com (search, categories, watch pages).
    """

    DEFAULT_ORIGIN = "https://www.ixxx.com"

    def __init__(self) -> None:
        self._ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self._impersonate = os.getenv("IXXX_CURL_IMPERSONATE", "chrome124").strip() or "chrome124"
        self._listing_timeout = _env_float("IXXX_LISTING_TIMEOUT", 35.0)
        self._watch_timeout = _env_float("IXXX_WATCH_TIMEOUT", 45.0)
        self._playwright_timeout_ms = _env_int("IXXX_PLAYWRIGHT_TIMEOUT_MS", 55000)
        self._default_max_listing_pages = _env_int("IXXX_MAX_LISTING_PAGES", 25)
        self._flare_url = os.getenv("IXXX_FLARESOLVERR_URL", "http://localhost:8191/v1").strip()
        self._use_flare = _env_bool("IXXX_USE_FLARESOLVERR", False)

    @property
    def name(self) -> str:
        return "iXXX"

    # ------------------------------------------------------------------ #
    # URL helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_ixxx_host(url: str) -> bool:
        try:
            host = urlparse(url).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            return host.endswith("ixxx.com")
        except Exception:
            return False

    def can_handle(self, url: str) -> bool:
        if not url or not self._is_ixxx_host(url):
            return False
        path = urlparse(url).path.lower()
        if not path or path == "/":
            return False
        # Listings
        if path.startswith("/c/") or path.startswith("/search"):
            return True
        # Typical watch URLs
        if _VIDEO_PATH_HINTS.search(path + "/"):
            return True
        # Query-style watch links
        if "viewkey" in path or re.search(r"videoid=\d+", url, re.I):
            return True
        return False

    @staticmethod
    def _absolute_url(base: str, href: str) -> str:
        if not href:
            return ""
        href = href.strip()
        if href.startswith("//"):
            return "https:" + href
        return urljoin(base, href)

    def _proxy_dict(self) -> Optional[Dict[str, str]]:
        """
        curl_cffi / httpx / Playwright expect different shapes; we return
        requests-style mapping for curl_cffi: {"http": url, "https": url}.
        """
        raw = (
            os.getenv("IXXX_HTTP_PROXY", "").strip()
            or os.getenv("HTTPS_PROXY", "").strip()
            or os.getenv("HTTP_PROXY", "").strip()
            or os.getenv("ALL_PROXY", "").strip()
        )
        if not raw:
            return None
        return {"http": raw, "https": raw}

    # ------------------------------------------------------------------ #
    # Fetch pipeline
    # ------------------------------------------------------------------ #

    def _browser_headers(self, referer: str) -> Dict[str, str]:
        return {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer or self.DEFAULT_ORIGIN + "/",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        }

    def _fetch_with_curl_cffi_sync(self, url: str, timeout: float, referer: str) -> Tuple[Optional[str], Optional[int]]:
        try:
            from curl_cffi import requests as cffi_req
        except ImportError:
            logger.debug("[iXXX] curl_cffi not installed; skipping TLS impersonation tier")
            return None, None

        proxies = self._proxy_dict()
        try:
            resp = cffi_req.get(
                url,
                impersonate=self._impersonate,
                headers=self._browser_headers(referer),
                timeout=timeout,
                proxies=proxies,
            )
            return resp.text, int(resp.status_code)
        except Exception as exc:
            logger.debug("[iXXX] curl_cffi fetch failed: %s", exc)
            return None, None

    async def _fetch_with_curl_cffi(self, url: str, timeout: float, referer: str) -> Tuple[Optional[str], Optional[int]]:
        return await asyncio.to_thread(self._fetch_with_curl_cffi_sync, url, timeout, referer)

    def _looks_like_challenge(self, html: Optional[str]) -> bool:
        if not html or len(html) < 800:
            return True
        low = html.lower()
        markers = (
            "cf-turnstile",
            "just a moment",
            "checking your browser",
            "enable javascript",
            "challenge-platform",
            "ray id",
        )
        return any(m in low for m in markers)

    async def _fetch_with_playwright(self, url: str, referer: str, timeout_ms: int) -> Optional[str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("[iXXX] Playwright not available")
            return None

        proxy = self._proxy_dict()
        pw_proxy = {"server": proxy["http"]} if proxy else None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=self._ua,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                proxy=pw_proxy,
            )
            page = await context.new_page()
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                    referer=referer or self.DEFAULT_ORIGIN + "/",
                )
                # Age / consent overlays (best-effort)
                for sel in (
                    'button:has-text("I am")',
                    'button:has-text("Enter")',
                    'button:has-text("Confirm")',
                    '[data-testid="agree"]',
                ):
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await asyncio.sleep(0.4)
                    except Exception:
                        pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(12000, timeout_ms // 3))
                except Exception:
                    pass
                html = await page.content()
                return html
            except Exception as exc:
                logger.warning("[iXXX] Playwright navigation failed: %s", exc)
                return None
            finally:
                await context.close()
                await browser.close()

    def _fetch_with_flaresolverr_sync(self, url: str, timeout_sec: float) -> Optional[str]:
        if not self._use_flare:
            return None
        try:
            import requests
        except ImportError:
            return None

        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": int(max(10_000, timeout_sec * 1000)),
        }
        try:
            r = requests.post(self._flare_url, json=payload, timeout=timeout_sec + 15)
            data = r.json()
            if data.get("status") != "ok":
                logger.warning("[iXXX] FlareSolverr status: %s", data.get("status"))
                return None
            sol = data.get("solution") or {}
            return sol.get("response")
        except Exception as exc:
            logger.warning("[iXXX] FlareSolverr request failed: %s", exc)
            return None

    async def _fetch_with_flaresolverr(self, url: str, timeout_sec: float) -> Optional[str]:
        return await asyncio.to_thread(self._fetch_with_flaresolverr_sync, url, timeout_sec)

    async def _fetch_html(
        self,
        url: str,
        *,
        kind: str = "watch",
    ) -> Optional[str]:
        """
        kind: 'watch' | 'listing' — selects timeout env.
        """
        referer = self.DEFAULT_ORIGIN + "/"
        timeout = self._watch_timeout if kind == "watch" else self._listing_timeout

        html, status = await self._fetch_with_curl_cffi(url, timeout, referer)
        if html and status == 200 and not self._looks_like_challenge(html):
            logger.info("[iXXX] curl_cffi OK (%s chars) for %s", len(html), url[:80])
            return html

        if html and status == 200:
            logger.debug("[iXXX] curl_cffi got challenge-like page, trying Playwright")

        logger.info("[iXXX] trying Playwright for %s", url[:80])
        pw_html = await self._fetch_with_playwright(url, referer, self._playwright_timeout_ms)
        if pw_html and not self._looks_like_challenge(pw_html):
            logger.info("[iXXX] Playwright OK (%s chars)", len(pw_html))
            return pw_html

        if self._use_flare:
            logger.info("[iXXX] trying FlareSolverr for %s", url[:80])
            flare_html = await self._fetch_with_flaresolverr(url, timeout)
            if flare_html:
                return flare_html

        # Last resort: return whatever we had if non-empty (caller may still parse)
        if html and len(html) > 500:
            logger.warning("[iXXX] returning possibly incomplete HTML after fallbacks")
            return html
        return pw_html or html

    # ------------------------------------------------------------------ #
    # Parsing helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _duration_text_to_seconds(text: str) -> int:
        if not text:
            return 0
        text = re.sub(r"[^\d:]+", "", text.strip())
        parts = [p for p in text.split(":") if p.isdigit()]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return 0
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 1:
            return nums[0]
        return 0

    @staticmethod
    def _meta_content(soup: BeautifulSoup, prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return ""

    def _pick_best_stream(self, html: str, candidate_urls: List[str]) -> Optional[str]:
        """Prefer highest resolution mp4 when filenames embed quality hints."""
        scored: List[Tuple[int, str]] = []
        quality_order = ("2160", "1440", "1080", "720", "480", "360")
        for u in candidate_urls:
            if not u or u.startswith("blob:"):
                continue
            score = 0
            lu = u.lower()
            for i, q in enumerate(quality_order):
                if q in lu:
                    score = 100 - i
                    break
            scored.append((score, u))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else None

    def _extract_stream_urls_from_html(self, html: str) -> List[str]:
        out: List[str] = []
        # Direct video tag
        for m in re.finditer(
            r'<source[^>]+src=["\']([^"\']+)["\']',
            html,
            re.I,
        ):
            out.append(m.group(1).replace("\\/", "/"))
        for m in re.finditer(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)(?:\?[^\s"\'<>]*)?', html, re.I):
            out.append(m.group(0))
        # Common JS assignments
        for pat in (
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
            r'["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
            r'videoUrl\s*[:=]\s*["\']([^"\']+)["\']',
            r'source\s*[:=]\s*["\']([^"\']+)["\']',
        ):
            for m in re.finditer(pat, html, re.I):
                out.append(m.group(1).replace("\\/", "/"))
        # Dedup preserve order
        seen = set()
        uniq: List[str] = []
        for u in out:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq

    async def _extract_with_playwright_watch(self, url: str) -> Tuple[Optional[str], List[str]]:
        """Return (html, intercepted media urls)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None, []

        referer = self.DEFAULT_ORIGIN + "/"
        proxy = self._proxy_dict()
        pw_proxy = {"server": proxy["http"]} if proxy else None
        media: List[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent=self._ua,
                viewport={"width": 1920, "height": 1080},
                proxy=pw_proxy,
            )
            page = await context.new_page()

            def on_response(resp) -> None:
                try:
                    u = resp.url
                    if any(x in u.lower() for x in (".m3u8", ".mp4")):
                        media.append(u)
                except Exception:
                    pass

            page.on("response", on_response)
            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._playwright_timeout_ms,
                    referer=referer,
                )
                await asyncio.sleep(1.5)
                try:
                    await page.wait_for_selector("video", timeout=8000)
                except Exception:
                    pass
                html = await page.content()
                return html, media
            except Exception as exc:
                logger.warning("[iXXX] watch Playwright failed: %s", exc)
                return None, media
            finally:
                await context.close()
                await browser.close()

    def _parse_listing_page(self, html: str, page_url: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        items: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # Strategy A: thumb tiles with anchors to /videos/...
        anchors = soup.select('a[href*="/videos/"], a[href*="/video/"], a[href*="/movie/"]')
        for a in anchors:
            href = a.get("href") or ""
            full = self._absolute_url(page_url, href)
            if not self._is_ixxx_host(full):
                continue
            if not _VIDEO_PATH_HINTS.search(urlparse(full).path + "/"):
                continue
            if full in seen:
                continue
            seen.add(full)

            title = (a.get("title") or "").strip() or a.get_text(" ", strip=True)
            if not title or len(title) < 2:
                continue

            thumb = ""
            img = a.find("img") or (a.parent and a.parent.find("img"))
            if img:
                thumb = (img.get("data-src") or img.get("data-original") or img.get("src") or "").strip()
            if thumb.startswith("//"):
                thumb = "https:" + thumb

            duration = 0
            dur_node = None
            for sel in (a.select_one(".duration"), a.select_one("[class*='duration']")):
                if sel:
                    dur_node = sel
                    break
            if not dur_node and a.parent:
                dur_node = a.parent.select_one(".duration, [class*='duration']")
            if dur_node:
                duration = self._duration_text_to_seconds(dur_node.get_text())

            w, h = 0, 0
            # data attributes sometimes hold dimensions
            for tag in (a, a.parent):
                if not tag:
                    continue
                for dw, dh in (("data-width", "data-height"),):
                    if tag.get(dw) and tag.get(dh):
                        try:
                            w, h = int(tag[dw]), int(tag[dh])
                        except (TypeError, ValueError):
                            pass

            items.append(
                {
                    "title": title[:500],
                    "url": full,
                    "source_url": page_url,
                    "thumbnail": thumb,
                    "duration": duration,
                    "width": w,
                    "height": h,
                    "source": self.name,
                }
            )

        logger.debug("[iXXX] parsed %s listing rows from %s", len(items), page_url[:80])
        return items

    def _get_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        # link[rel=next]
        nxt = soup.find("link", rel=lambda x: x and "next" in str(x).lower())
        if nxt and nxt.get("href"):
            return self._absolute_url(current_url, nxt["href"])

        for a in soup.select('a[rel="next"], a.link_next, .pagination a.next, a[aria-label="Next"]'):
            href = a.get("href")
            if href:
                return self._absolute_url(current_url, href)

        # Query param pagination
        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        for key in ("page", "p", "pageNumber"):
            if key in qs:
                try:
                    cur = int(qs[key][0])
                except (ValueError, IndexError):
                    cur = 1
                qs[key] = [str(cur + 1)]
                new_q = urlencode(qs, doseq=True)
                return urlunparse(
                    (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_q, parsed.fragment)
                )

        # /page/2/ style
        m = re.search(r"/(?:page)[/-](\d+)/?", current_url, re.I)
        if m:
            n = int(m.group(1)) + 1
            return re.sub(r"/(?:page)[/-](\d+)/?", f"/page/{n}/", current_url, count=1, flags=re.I)

        return None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def extract_listing(self, url: str, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Crawl a category or search URL. Does not resolve stream_url per item.
        """
        if max_pages is None:
            max_pages = self._default_max_listing_pages
        max_pages = max(1, min(max_pages, 200))

        aggregated: List[Dict[str, Any]] = []
        page_url: Optional[str] = url
        visited = 0

        while page_url and visited < max_pages:
            visited += 1
            html = await self._fetch_html(page_url, kind="listing")
            if not html:
                logger.warning("[iXXX] listing fetch failed for %s", page_url)
                break

            batch = self._parse_listing_page(html, page_url)
            aggregated.extend(batch)

            soup = BeautifulSoup(html, "lxml")
            nxt = self._get_next_page_url(soup, page_url)
            if not nxt or nxt == page_url:
                break
            page_url = nxt

        # Dedupe by url
        out: List[Dict[str, Any]] = []
        seen_u: set[str] = set()
        for row in aggregated:
            u = row.get("url")
            if not u or u in seen_u:
                continue
            seen_u.add(u)
            out.append(row)

        logger.info("[iXXX] extract_listing collected %s items (%s pages)", len(out), visited)
        return out

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        if not self.can_handle(url):
            logger.debug("[iXXX] can_handle false for %s", url)
            return None

        html = await self._fetch_html(url, kind="watch")
        stream_urls: List[str] = []

        if html:
            stream_urls.extend(self._extract_stream_urls_from_html(html))
            soup = BeautifulSoup(html, "lxml")
            title = self._meta_content(soup, "og:title") or ""
            if not title:
                t = soup.find("title")
                if t:
                    title = t.get_text(" ", strip=True)
            thumb = self._meta_content(soup, "og:image")
            duration = 0
            d1 = self._meta_content(soup, "video:duration")
            if d1.isdigit():
                duration = int(d1)
            if not duration:
                m = re.search(r'"duration"\s*:\s*"?(\d+)"?', html)
                if m:
                    duration = int(m.group(1))

            stream_url = self._pick_best_stream(html, stream_urls)

            if stream_url:
                height = 0
                for q in ("2160", "1440", "1080", "720", "480", "360"):
                    if q in stream_url:
                        height = int(q)
                        break
                width = {2160: 3840, 1440: 2560, 1080: 1920, 720: 1280, 480: 854, 360: 640}.get(height, 0)
                return {
                    "id": None,
                    "title": title or "iXXX",
                    "description": "",
                    "thumbnail": thumb,
                    "duration": duration,
                    "stream_url": stream_url,
                    "width": width,
                    "height": height,
                    "tags": [],
                    "uploader": "",
                    "is_hls": ".m3u8" in stream_url.lower(),
                }

        # Deeper Playwright pass for media URLs
        pw_html, intercepted = await self._extract_with_playwright_watch(url)
        combined = list(stream_urls)
        if intercepted:
            combined.extend(intercepted)
        if pw_html:
            combined.extend(self._extract_stream_urls_from_html(pw_html))
            soup = BeautifulSoup(pw_html, "lxml")
            title = self._meta_content(soup, "og:title") or ""
            thumb = self._meta_content(soup, "og:image")
        else:
            title, thumb = "", ""

        stream_url = self._pick_best_stream(pw_html or "", combined)
        if stream_url:
            is_hls = ".m3u8" in stream_url.lower()
            return {
                "id": None,
                "title": title or "iXXX",
                "description": "",
                "thumbnail": thumb,
                "duration": 0,
                "stream_url": stream_url,
                "width": 1920 if is_hls else 0,
                "height": 1080 if is_hls else 0,
                "tags": [],
                "uploader": "",
                "is_hls": is_hls,
            }

        # yt-dlp fallback (optional)
        try:
            import yt_dlp
        except ImportError:
            logger.warning("[iXXX] extract failed completely for %s", url[:80])
            return None

        logger.info("[iXXX] falling back to yt-dlp for %s", url[:80])
        try:

            def _run() -> Optional[Dict[str, Any]]:
                ytdlp_opts: Dict[str, Any] = {
                    "quiet": True,
                    "ignoreerrors": True,
                    "no_warnings": True,
                    "socket_timeout": 20,
                    "retries": 2,
                }
                if self._proxy_dict():
                    ytdlp_opts["proxy"] = self._proxy_dict()["https"]
                with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return None
                    stream = info.get("url")
                    if not stream:
                        for f in info.get("formats") or []:
                            if f.get("url"):
                                stream = f["url"]
                                break
                    if not stream:
                        return None
                    return {
                        "title": info.get("title") or "iXXX",
                        "thumbnail": info.get("thumbnail"),
                        "duration": int(info.get("duration") or 0),
                        "stream_url": stream,
                        "width": info.get("width") or 0,
                        "height": info.get("height") or 0,
                        "is_hls": ".m3u8" in str(stream).lower(),
                    }

            meta = await asyncio.to_thread(_run)
            if meta:
                return {
                    "id": None,
                    "title": meta["title"],
                    "description": "",
                    "thumbnail": meta.get("thumbnail"),
                    "duration": meta["duration"],
                    "stream_url": meta["stream_url"],
                    "width": meta.get("width") or 0,
                    "height": meta.get("height") or 0,
                    "tags": [],
                    "uploader": "",
                    "is_hls": meta.get("is_hls", False),
                }
        except Exception as exc:
            logger.error("[iXXX] yt-dlp fallback failed: %s", exc)

        return None


# -----------------------------------------------------------------------------
# Registration (manual steps — also wired in app/extractors/__init__.py)
# -----------------------------------------------------------------------------
#
# 1) ExtractorRegistry (VIP / import by URL):
#    from app.extractors.registry import ExtractorRegistry
#    from app.extractors.ixxx import IxxxExtractor
#    ExtractorRegistry.register(IxxxExtractor())   # idempotent check by name in init_registry
#
# 2) Discovery search key (source_catalog):
#    Add "ixxx" to DISCOVERY_SEARCH_SOURCE_KEYS, aliases, DISCOVERY_SOURCE_OPTIONS,
#    and _LIBRARY_URL_SOURCE_RULES for health labels.
#
# 3) ExternalSearchEngine:
#    In _run_single_discovery_source dispatch, map 'ixxx': self.search_ixxx_async.
#    Implement search_ixxx_async to build the search URL and call extract_listing().
#
# Proxy: use HTTP_PROXY / HTTPS_PROXY / ALL_PROXY or IXXX_HTTP_PROXY. The project's
# WebshareAPI (webshare.cz) is for file hosting, not an HTTP proxy — use a real proxy URL.
# -----------------------------------------------------------------------------
