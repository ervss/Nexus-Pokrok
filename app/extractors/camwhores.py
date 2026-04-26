"""
Camwhores.tv resolver for watch pages (/videos/...).

Primary path uses Playwright so site JS and Cloudflare checks run in a real
browser context. If that fails, fall back to the legacy HTML/regex scraper.
"""
import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

logger = logging.getLogger(__name__)


def normalize_camwhores_get_file_rnd(url: str) -> str:
    """
    CamWhores direct file URLs use query param rnd=<unix_ms>. Extension-captured links
    always include it; HTML extraction sometimes omits it. Always set/refresh rnd so
    playback and probes match the working URL shape.
    """
    if not url:
        return url
    low = url.lower()
    if "camwhores.tv" not in low or "get_file" not in low:
        return url
    try:
        parsed = urlparse(url)
        pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "rnd"]
        pairs.append(("rnd", str(int(time.time() * 1000))))
        new_q = urlencode(pairs)
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_q, parsed.fragment)
        )
    except Exception as exc:
        logger.debug("[Camwhores] normalize rnd urlparse failed, regex fallback: %s", exc)
        ms = int(time.time() * 1000)
        if re.search(r"[?&]rnd=\d+", url, re.I):
            return re.sub(r"(?<=[?&])rnd=\d+", f"rnd={ms}", url, count=1, flags=re.I)
        sep = "&" if ("?" in url) else "?"
        return f"{url}{sep}rnd={ms}"


class CamwhoresExtractor:
    def __init__(self) -> None:
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self.page_timeout_ms = int(os.getenv("CAMWHORES_PLAYWRIGHT_TIMEOUT_MS", "45000"))
        self.network_idle_timeout_ms = int(os.getenv("CAMWHORES_NETWORK_IDLE_TIMEOUT_MS", "15000"))
        self.probe_timeout_secs = int(os.getenv("CAMWHORES_PROBE_TIMEOUT_SECS", "12"))
        self.max_probe_candidates = int(os.getenv("CAMWHORES_MAX_PROBE_CANDIDATES", "8"))

    @property
    def name(self) -> str:
        return "Camwhores"

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = url.lower()
        return "camwhores.tv" in u and "/videos/" in u

    @staticmethod
    def _normalize_watch_url(url: str) -> str:
        if not url:
            return ""
        cleaned = url.strip()
        if "camwhores.tv" in cleaned.lower() and "/videos/" in cleaned.lower():
            return cleaned.rstrip("/") + "/"
        return cleaned

    @staticmethod
    def _sanitize_url(raw: str) -> str:
        if not raw:
            return ""
        url = raw.replace("\\/", "/").strip()
        if "function/0/" in url:
            url = url.split("function/0/", 1)[-1]
        if url.startswith("//"):
            url = "https:" + url
        http_idx = url.find("http://")
        https_idx = url.find("https://")
        if https_idx > 0:
            url = url[https_idx:]
        elif http_idx > 0:
            url = url[http_idx:]
        return url

    @staticmethod
    def _infer_height_from_url(url: str) -> int:
        if not url:
            return 0
        m = re.search(r"[/_](2160|1440|1080|720|480|360)p(?:[/_.-]|$)", url, re.I) or re.search(
            r"/(2160|1440|1080|720|480|360)/", url
        )
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
        if "4k" in url.lower():
            return 2160
        return 0

    @staticmethod
    def _width_for_height(height: int) -> int:
        return {
            2160: 3840,
            1440: 2560,
            1080: 1920,
            720: 1280,
            480: 854,
            360: 640,
        }.get(height, 0)

    @staticmethod
    def _safe_duration_secs(v: int) -> int:
        return v if 10 <= v <= 21600 else 0

    @staticmethod
    def _resolve_cookie_file_path() -> Optional[str]:
        env = os.getenv("CAMWHORES_COOKIE_FILE", "").strip()
        if env and os.path.isfile(env):
            return env
        here = Path(__file__).resolve()
        repo_root = here.parents[2]
        for candidate in (Path.cwd() / "camwhores.cookies.txt", repo_root / "camwhores.cookies.txt"):
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def _parse_netscape_cookie_file(path: str) -> List[Dict[str, Any]]:
        """Netscape format (Export from browser extension). Domain must mention camwhores."""
        out: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 7:
                        continue
                    domain = (parts[0] or "").strip()
                    if "camwhores" not in domain.lower():
                        continue
                    secure = parts[3] == "TRUE"
                    try:
                        exp_raw = parts[4]
                        expires = int(exp_raw) if exp_raw and exp_raw.isdigit() and int(exp_raw) > 0 else -1
                    except ValueError:
                        expires = -1
                    path_s = parts[2] or "/"
                    name, value = parts[5], parts[6].strip()
                    if not name:
                        continue
                    entry: Dict[str, Any] = {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": path_s,
                        "httpOnly": False,
                        "secure": secure,
                    }
                    if expires > 0:
                        entry["expires"] = expires
                    out.append(entry)
        except OSError as exc:
            logger.warning("[Camwhores] cannot read cookie file %s: %s", path, exc)
        return out

    @staticmethod
    def _parse_inline_cookie_header(header: str) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        if not header:
            return pairs
        for part in header.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            if not name:
                continue
            pairs[name] = value.strip()
        return pairs

    def _cookie_bundle(self) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Merge cookies from (1) camwhores.cookies.txt / CAMWHORES_COOKIE_FILE,
        (2) CAMWHORES_COOKIE env. Env wins on name collision.
        Returns (Cookie header string, list for Playwright add_cookies).
        """
        by_name: Dict[str, str] = {}
        pw: List[Dict[str, Any]] = []

        path = self._resolve_cookie_file_path()
        if path:
            for c in self._parse_netscape_cookie_file(path):
                by_name[c["name"]] = c["value"]
                pw.append(dict(c))

        env_pairs = self._parse_inline_cookie_header(os.getenv("CAMWHORES_COOKIE", "").strip())
        for name, value in env_pairs.items():
            by_name[name] = value
            pw = [x for x in pw if x.get("name") != name]
            pw.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".camwhores.tv",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": False,
                    "secure": True,
                }
            )

        header = "; ".join(f"{k}={v}" for k, v in sorted(by_name.items())) if by_name else ""
        if path or by_name:
            logger.info(
                "[Camwhores] cookies: file=%s names=%s",
                path or "(none)",
                len(by_name),
            )
        return header, pw

    def _base_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer or "https://www.camwhores.tv/",
        }
        cookie_header, _ = self._cookie_bundle()
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    def _playwright_cookies(self) -> List[Dict[str, Any]]:
        _, cookies = self._cookie_bundle()
        return cookies

    def _extract_title(self, html: str, fallback: str = "Camwhores Video") -> str:
        for pat in (
            r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
            r"<title>([^<]+)</title>",
        ):
            m = re.search(pat, html or "", re.I)
            if m:
                return m.group(1).strip()
        return fallback

    def _extract_thumbnail(self, html: str) -> Optional[str]:
        for pat in (
            r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
            r'<video[^>]+poster=["\']([^"\']+)["\']',
        ):
            m = re.search(pat, html or "", re.I)
            if m:
                thumb = m.group(1).strip()
                if thumb.startswith("//"):
                    thumb = "https:" + thumb
                return thumb
        return None

    def _extract_duration(self, html: str) -> int:
        dm = re.search(
            r'<meta\s+property=["\']video:duration["\']\s+content=["\'](\d+)["\']',
            html or "",
            re.I,
        )
        if dm:
            try:
                return self._safe_duration_secs(int(dm.group(1)))
            except ValueError:
                pass
        for pat in (
            r'"duration"\s*:\s*"?(\d{2,6})"?',
            r"video_duration['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"'duration'\s*:\s*'(\d+)'",
            r'"video_duration"\s*:\s*(\d+)',
        ):
            mm = re.search(pat, html or "", re.I)
            if mm:
                try:
                    d = self._safe_duration_secs(int(mm.group(1)))
                    if d:
                        return d
                except ValueError:
                    pass
        return 0

    def _extract_candidates_from_html(self, html: str) -> List[str]:
        candidates: List[str] = []
        for pat in (
            r"video_url\s*=\s*['\"]([^'\"]+)['\"]",
            r"(https://(?:www\.)?camwhores\.tv/get_file/[^\"'\s<>]+)",
            r'"file"\s*:\s*"([^"]+get_file[^"]+)"',
            r"'file'\s*:\s*'([^']+get_file[^']+)'",
        ):
            matches = re.findall(pat, html or "", re.I)
            for raw in matches:
                cleaned = self._sanitize_url(raw).rstrip()
                if cleaned and "get_file" in cleaned and cleaned.startswith("http"):
                    candidates.append(cleaned)
        deduped = list(dict.fromkeys(candidates))
        deduped.sort(key=lambda f: (self._infer_height_from_url(f), len(f)), reverse=True)
        return deduped

    async def _probe_candidates(self, candidates: List[str], watch_url: str) -> Optional[str]:
        if not candidates:
            return None
        headers = self._base_headers(referer=watch_url)
        timeout = aiohttp.ClientTimeout(total=self.probe_timeout_secs)
        async with aiohttp.ClientSession() as session:
            for candidate in candidates[: self.max_probe_candidates]:
                try:
                    probe_url = normalize_camwhores_get_file_rnd(candidate)
                    probe_headers = {**headers, "Referer": watch_url, "Range": "bytes=0-0"}
                    async with session.get(
                        probe_url,
                        headers=probe_headers,
                        timeout=timeout,
                        allow_redirects=True,
                    ) as probe:
                        ctype = (probe.headers.get("Content-Type") or "").lower()
                        clen = int(probe.headers.get("Content-Length") or 0)
                        ok = probe.status in (200, 206) and (
                            probe.status == 206 or "video" in ctype or clen >= 65536
                        )
                        if ok:
                            return normalize_camwhores_get_file_rnd(candidate)
                        logger.info(
                            "[Camwhores] candidate rejected status=%s ctype=%s len=%s url=%s",
                            probe.status,
                            ctype,
                            clen,
                            candidate[:140],
                        )
                except Exception as exc:
                    logger.info("[Camwhores] candidate probe failed for %s: %s", candidate[:140], exc)
        return normalize_camwhores_get_file_rnd(candidates[0]) if candidates else None

    async def _legacy_extract_html(self, url: str) -> Optional[str]:
        headers = self._base_headers()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    logger.warning("[Camwhores] http_%s for %s", resp.status, url)
                    return None
                return await resp.text()

    async def _extract_with_playwright(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.warning("[Camwhores] Playwright unavailable: %s", exc)
            return None

        network_urls: List[str] = []
        watch_url = self._normalize_watch_url(url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1440, "height": 1024},
                locale="en-US",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            cookies = self._playwright_cookies()
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()

            def _collect_url(candidate_url: str) -> None:
                cleaned = self._sanitize_url(candidate_url).rstrip()
                if cleaned and "get_file" in cleaned and cleaned not in network_urls:
                    network_urls.append(cleaned)

            page.on("request", lambda request: _collect_url(request.url))
            page.on("response", lambda response: _collect_url(response.url))

            try:
                logger.info("[Camwhores] Playwright fetching %s", watch_url)
                await page.goto(watch_url, wait_until="domcontentloaded", timeout=self.page_timeout_ms)

                for selector in (
                    'button:has-text("I am 18")',
                    'button:has-text("Enter")',
                    'button:has-text("Accept")',
                    ".btn-enter",
                    ".age-confirm",
                    "[data-action='confirm']",
                ):
                    try:
                        btn = await page.query_selector(selector)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        continue

                try:
                    await page.wait_for_load_state("networkidle", timeout=self.network_idle_timeout_ms)
                except PlaywrightTimeoutError:
                    logger.info("[Camwhores] Playwright networkidle timeout for %s", watch_url)

                # Trigger player/network activity if the page waits for interaction.
                try:
                    await page.evaluate(
                        """() => {
                            const v = document.querySelector('video');
                            if (v) {
                                v.muted = true;
                                const p = v.play();
                                if (p && typeof p.catch === 'function') p.catch(() => {});
                            }
                        }"""
                    )
                    await asyncio.sleep(2)
                except Exception:
                    pass

                page_meta = await page.evaluate(
                    """() => {
                        const meta = {
                            title: document.querySelector('meta[property="og:title"]')?.content || '',
                            thumbnail: document.querySelector('meta[property="og:image"]')?.content || document.querySelector('video')?.poster || '',
                            duration: 0,
                            sources: [],
                        };
                        const durMeta = document.querySelector('meta[property="video:duration"]')?.content;
                        if (durMeta && /^\\d+$/.test(durMeta)) {
                            meta.duration = parseInt(durMeta, 10);
                        }
                        document.querySelectorAll('video[src], video source[src]').forEach((node) => {
                            const src = node.getAttribute('src');
                            if (src) meta.sources.push(src);
                        });
                        if (!meta.title) {
                            const h1 = document.querySelector('h1');
                            meta.title = h1 ? h1.textContent : document.title;
                        }
                        return meta;
                    }"""
                )
                html = await page.content()
            except Exception as exc:
                logger.warning("[Camwhores] Playwright extract failed for %s: %s", watch_url, exc)
                return None
            finally:
                await browser.close()

        html_candidates = self._extract_candidates_from_html(html)
        for raw in page_meta.get("sources") or []:
            cleaned = self._sanitize_url(raw).rstrip()
            if cleaned and "get_file" in cleaned and cleaned not in html_candidates:
                html_candidates.append(cleaned)
        candidates = list(dict.fromkeys(network_urls + html_candidates))
        candidates.sort(key=lambda f: (self._infer_height_from_url(f), len(f)), reverse=True)

        if not candidates:
            logger.warning("[Camwhores] Playwright found no get_file URLs for %s", watch_url)
            return None

        stream_url = await self._probe_candidates(candidates, watch_url)
        if not stream_url:
            logger.warning("[Camwhores] Playwright failed to validate get_file URLs for %s", watch_url)
            return None

        duration = self._safe_duration_secs(int(page_meta.get("duration") or 0)) or self._extract_duration(html)
        return {
            "html": html,
            "title": (page_meta.get("title") or "").strip() or self._extract_title(html),
            "thumbnail": (page_meta.get("thumbnail") or "").strip() or self._extract_thumbnail(html),
            "duration": duration,
            "stream_url": stream_url,
            "height": self._infer_height_from_url(stream_url),
            "_resolver": "playwright",
            "_prevalidated": True,
        }

    async def _extract_with_http_fallback(self, url: str) -> Optional[Dict[str, Any]]:
        html = await self._legacy_extract_html(url)
        if not html or len(html) < 1200:
            logger.warning("[Camwhores] too short response for %s", url)
            return None

        candidates = self._extract_candidates_from_html(html)
        stream_url = await self._probe_candidates(candidates, url)
        if not stream_url:
            logger.warning("[Camwhores] no get_file found for %s", url)
            return None

        return {
            "html": html,
            "title": self._extract_title(html),
            "thumbnail": self._extract_thumbnail(html),
            "duration": self._extract_duration(html),
            "stream_url": stream_url,
            "height": self._infer_height_from_url(stream_url),
            "_resolver": "http-fallback",
            "_prevalidated": True,
        }

    def _build_result(self, watch_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        stream_url = normalize_camwhores_get_file_rnd(payload["stream_url"])
        inferred_height = int(payload.get("height") or self._infer_height_from_url(stream_url))
        return {
            "id": None,
            "title": payload.get("title") or "Camwhores Video",
            "description": "",
            "thumbnail": payload.get("thumbnail"),
            "duration": int(payload.get("duration") or 0),
            "stream_url": stream_url,
            "width": self._width_for_height(inferred_height),
            "height": inferred_height,
            "tags": [],
            "uploader": "",
            "is_hls": False,
            "source_url": watch_url,
            "_resolver": payload.get("_resolver"),
            "_prevalidated": bool(payload.get("_prevalidated")),
        }

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        watch_url = self._normalize_watch_url(url)
        if not self.can_handle(watch_url):
            logger.warning("[Camwhores] unsupported URL: %s", url)
            return None

        try:
            payload = await self._extract_with_playwright(watch_url)
            if payload and payload.get("stream_url"):
                logger.info("[Camwhores] resolved via %s: %s", payload.get("_resolver"), watch_url)
                return self._build_result(watch_url, payload)

            payload = await self._extract_with_http_fallback(watch_url)
            if payload and payload.get("stream_url"):
                logger.info("[Camwhores] resolved via %s: %s", payload.get("_resolver"), watch_url)
                return self._build_result(watch_url, payload)

            logger.warning("[Camwhores] all extraction paths failed for %s", watch_url)
            return None
        except Exception as exc:
            logger.error("[Camwhores] extract failed: %s", exc, exc_info=True)
            return None
