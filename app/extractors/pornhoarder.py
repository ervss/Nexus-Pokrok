import re
import json
import logging
import requests
from .base import VideoExtractor
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

class PornHoarderExtractor(VideoExtractor):

    @property
    def name(self) -> str:
        return "PornHoarder"

    @property
    def domains(self):
        return ["pornhoarder.io", "pornhoarder.net", "pornhoarder.pictures"]

    def can_handle(self, url: str) -> bool:
        return any(d in (url or "").lower() for d in self.domains)

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            headers = {
                "User-Agent": UA,
                "Referer": "https://pornhoarder.io/",
                "Accept-Language": "en-US,en;q=0.9",
            }

            # If we received a player.php URL, try to resolve it back to a watch page
            # to get metadata; also fetch the player page for the direct stream
            player_url = None
            watch_url = url

            if "player.php" in url:
                player_url = url
                # Derive watch URL from player — can't easily reverse, just use player URL as source
                watch_url = url
            elif "/watch/" in url:
                # Build player URL from watch page iframe
                pass

            # ── 1. Fetch watch page (or player page) ──────────────────────────
            resp = requests.get(watch_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.warning("[PornHoarder] HTTP %s for %s", resp.status_code, watch_url)
                return None
            html = resp.text

            # ── 2. JSON-LD metadata ───────────────────────────────────────────
            title = ""
            thumbnail = ""
            duration = 0
            embed_url = ""

            ld_match = re.search(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                html, re.DOTALL | re.IGNORECASE
            )
            if ld_match:
                try:
                    ld = json.loads(ld_match.group(1))
                    title = ld.get("name", "")
                    thumbnail = ld.get("thumbnailUrl", "") or ld.get("thumbnail", {}).get("url", "")
                    if isinstance(thumbnail, list):
                        thumbnail = thumbnail[0] if thumbnail else ""
                    elif isinstance(thumbnail, dict):
                        thumbnail = thumbnail.get("url", "") or thumbnail.get("src", "")
                    embed_url = ld.get("embedUrl", "")
                    dur_raw = ld.get("duration", "")
                    if dur_raw:
                        dm = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur_raw, re.I)
                        if dm:
                            duration = (int(dm.group(1) or 0) * 3600 +
                                        int(dm.group(2) or 0) * 60 +
                                        int(dm.group(3) or 0))
                except Exception as e:
                    logger.debug("[PornHoarder] JSON-LD parse error: %s", e)

            # Fallback meta tags
            if not title:
                m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
                title = m.group(1).replace("| Watch on PornHoarder.io", "").strip() if m else "PornHoarder Video"
            if not thumbnail:
                m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
                thumbnail = m.group(1) if m else ""

            # ── 3. Get embed/player URL if not in JSON-LD ────────────────────
            if not embed_url and not player_url:
                m = re.search(r'<iframe[^>]+src=["\']([^"\']*pornhoarder\.net/player[^"\']*)["\']', html, re.I)
                if m:
                    embed_url = m.group(1)

            # ── 4. Fetch player page to get direct stream URL ─────────────────
            stream_url = None
            fetch_player = player_url or embed_url

            if fetch_player:
                try:
                    ph = requests.get(fetch_player, headers={
                        **headers,
                        "Referer": watch_url,
                    }, timeout=15)
                    player_html = ph.text if ph.status_code == 200 else ""

                    # Look for direct mp4/m3u8 in player page
                    for pattern in [
                        r'["\']?(https?://[^"\'>\s]+\.mp4[^"\'>\s]*)["\']?',
                        r'["\']?(https?://[^"\'>\s]+\.m3u8[^"\'>\s]*)["\']?',
                        r'file\s*:\s*["\']?(https?://[^"\'>\s]+)["\']?',
                        r'src\s*:\s*["\']?(https?://[^"\'>\s]+\.(?:mp4|m3u8)[^"\'>\s]*)["\']?',
                    ]:
                        m = re.search(pattern, player_html, re.I)
                        if m:
                            candidate = m.group(1).replace("\\/", "/")
                            if "pornhoarder" not in candidate.lower() or ".mp4" in candidate.lower() or ".m3u8" in candidate.lower():
                                stream_url = candidate
                                break

                    # Also check for jwplayer setup / playerjs config
                    if not stream_url:
                        m = re.search(r'setup\s*\(\s*\{.*?"file"\s*:\s*"([^"]+)"', player_html, re.DOTALL)
                        if m:
                            stream_url = m.group(1).replace("\\/", "/")

                except Exception as e:
                    logger.warning("[PornHoarder] player fetch error: %s", e)

            # ── 5. Try direct video element in watch page ─────────────────────
            if not stream_url:
                m = re.search(r'<source[^>]+src=["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']', html, re.I)
                if m:
                    stream_url = m.group(1)

            # ── 6. Try provider embed URLs (filemoon, voe, streamtape, dood, etc.) ──
            PROVIDER_PATTERNS = [
                r'(?:https?://)?(?:www\.)?filemoon\.[a-z]+/[a-z]/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?voe\.sx/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?streamtape\.[a-z]+/[a-z]/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?dood(?:stream)?\.[a-z]+/[a-z]/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?bigwarp\.[a-z]+/[a-z]/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?lulustream\.[a-z]+/[a-zA-Z0-9_-]+',
                r'(?:https?://)?(?:www\.)?netu\.[a-z]+/[a-zA-Z0-9_-]+',
            ]
            provider_url = None
            for pat in PROVIDER_PATTERNS:
                m = re.search(pat, html, re.I)
                if m:
                    candidate = m.group(0)
                    if not candidate.startswith('http'):
                        candidate = 'https://' + candidate
                    provider_url = candidate
                    logger.info("[PornHoarder] found provider embed: %s", provider_url)
                    break

            # ── 7. Fallback: use provider URL or embed URL ─────────────────────
            if not stream_url:
                stream_url = provider_url or embed_url or watch_url
                if not provider_url:
                    logger.warning("[PornHoarder] no direct stream found, using embed URL: %s", stream_url)

            # ── 8. Size from .video-info ──────────────────────────────────────
            filesize = 0
            size_m = re.search(r'([\d.]+)\s*(GB|MB)\b', html, re.I)
            if size_m:
                n = float(size_m.group(1))
                unit = size_m.group(2).upper()
                filesize = int(n * (1073741824 if unit == "GB" else 1048576))

            # ── 9. Quality guess ──────────────────────────────────────────────
            height = 720
            for pat, h in [("4k|2160p", 2160), ("1080p|fhd", 1080), ("720p", 720), ("480p", 480)]:
                if re.search(pat, title + html[:2000], re.I):
                    height = h
                    break
            width = {2160: 3840, 1080: 1920, 720: 1280, 480: 854}.get(height, 1280)

            is_hls = ".m3u8" in (stream_url or "")

            logger.info("[PornHoarder] extracted: %s | stream=%s | dur=%ss",
                        title[:60], (stream_url or "")[:80], duration)

            normalized_player_url = (player_url or embed_url or provider_url or "")
            if isinstance(normalized_player_url, str):
                normalized_player_url = normalized_player_url.replace("/player.php?", "/player_t.php?")

            return {
                "id": None,
                "title": title,
                "description": "",
                "thumbnail": thumbnail,
                "duration": duration,
                "stream_url": stream_url,
                "player_url": normalized_player_url,
                "width": width,
                "height": height,
                "filesize": filesize,
                "tags": [],
                "uploader": "",
                "is_hls": is_hls,
            }

        except Exception as e:
            logger.error("[PornHoarder] extract failed for %s: %s", url, e, exc_info=True)
            return None
