import logging
import re
import asyncio
from typing import Optional, Dict, Any, List
import base64
import urllib.parse
from bs4 import BeautifulSoup
import httpx
from .base import VideoExtractor

logger = logging.getLogger(__name__)

class BunkrExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "Bunkr"

    def can_handle(self, url: str) -> bool:
        # scdn.st is a CDN-only domain — direct file links, not extractable pages
        page_mirrors = ["bunkr.la", "bunkr.si", "bunkr.is", "bunkr-albums.io", "bunkr.cr",
                        "bunkr.black", "bunkr.su", "bunkr.pk", "bunkrr.su", "bunkr.ws",
                        "bunkr.vc", "bunkr.media", "bunkr.ru", "bunkr.to", "bunkr.ac",
                        "bunkr.ph", "bunkr.sk", "bunkr.ps", "bunkr.fi"]
        lower = url.lower()
        if not any(x in lower for x in page_mirrors):
            return False
        # Bunkr file/video page routes are extractable even when slug ends with .mp4.
        if re.search(r"/(f|v)/", lower):
            return True
        # Reject direct CDN file links (no page to scrape)
        path = lower.split('?')[0].split('#')[0]
        if re.search(r'\.(mp4|mkv|mov|webm|m4v|avi)$', path):
            return False
        return True

    def _decode_bunkr_vs_url(self, encoded: str, timestamp: int) -> Optional[str]:
        """
        Decode URL from /api/vs response.
        Mirrors player.enc.js logic:
        key = "SECRET_KEY_" + floor(timestamp/3600)
        decoded = xor(base64_decode(url), key)
        """
        if not encoded:
            return None
        try:
            raw = base64.b64decode(encoded)
            key = f"SECRET_KEY_{int(timestamp // 3600)}".encode("utf-8")
            out = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
            return out.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.debug(f"Bunkr URL decode failed: {e}")
            return None

    async def _api_resolve(self, client: httpx.AsyncClient, page_url: str, slug: str) -> Optional[str]:
        """Resolve direct stream URL using Bunkr page API (/api/vs)."""
        parsed = urllib.parse.urlparse(page_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        try:
            resp = await client.post(
                f"{origin}/api/vs",
                json={"slug": slug},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Referer": page_url,
                    "Origin": origin,
                },
                timeout=12,
            )
            if resp.status_code == 200:
                data = resp.json()
                u = data.get("url")
                if u:
                    if data.get("encrypted"):
                        u = self._decode_bunkr_vs_url(u, int(data.get("timestamp") or 0))
                    if u:
                        return ("https:" + u) if str(u).startswith("//") else str(u)
        except Exception as e:
            logger.debug(f"Bunkr /api/vs resolve failed for {slug}: {e}")
        return None

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extracts metadata and direct stream URL from a Bunkr file page (/f/ or /v/).
        Uses Bunkr private API first (reliable), falls back to HTML parsing.
        """
        base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Referer': 'https://bunkr.cr/',
        }
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or ""
        slug = path.rstrip('/').split('/')[-1]
        # For /f/<slug>.mp4 style page URLs, /api/vs expects slug without extension.
        slug_no_ext = re.sub(r'\.(mp4|mkv|mov|webm|m4v|avi)$', '', slug, flags=re.I)

        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=base_headers, verify=False) as client:

                # --- Step 1: Bunkr page API (/api/vs) used by player.enc.js ---
                stream_url = await self._api_resolve(client, url, slug_no_ext or slug)
                if not stream_url and slug_no_ext != slug:
                    stream_url = await self._api_resolve(client, url, slug)
                if stream_url:
                    logger.info(f"Bunkr /api/vs resolved {slug} -> {stream_url[:80]}")

                # --- Step 2: HTML parse fallback (Bunkr is JS-rendered; may still have some static data) ---
                title = ""
                thumbnail = ""
                html = ""
                soup = None

                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        html = resp.text
                        soup = BeautifulSoup(html, 'html.parser')
                except Exception:
                    pass

                if soup:
                    og_title = soup.find('meta', property='og:title')
                    if og_title:
                        title = og_title.get('content', '').strip()
                    if not title:
                        t = soup.find('title')
                        if t:
                            title = t.text.replace(' - Bunkr', '').strip()

                    og_image = soup.find('meta', property='og:image')
                    if og_image:
                        thumbnail = og_image.get('content', '').strip()
                        if thumbnail.startswith('//'):
                            thumbnail = 'https:' + thumbnail

                    # Fallback stream detection from HTML (works on non-JS pages)
                    if not stream_url:
                        video_tag = soup.find('video')
                        if video_tag:
                            src = (video_tag.find('source') or {}).get('src') or video_tag.get('src')
                            if src and not src.startswith('blob:') and src not in ('/', '#'):
                                stream_url = ('https:' + src) if src.startswith('//') else src

                    if not stream_url:
                        for a in soup.find_all('a', href=True):
                            h = a['href']
                            if any(x in h for x in ['.mp4', '.mkv', '.webm', 'media-files', 'scdn.st']):
                                if h.startswith('//'): h = 'https:' + h
                                elif h.startswith('/'): h = f"https://{url.split('/')[2]}{h}"
                                stream_url = h; break

                    if not stream_url and html:
                        m = re.search(r'https?://[a-z0-9.-]+\.(?:st|su|io|is|si|la)/[a-zA-Z0-9_-]+\.(?:mp4|mkv|mov|webm)', html)
                        if m:
                            stream_url = m.group(0)

                if not stream_url:
                    logger.warning(f"Bunkr extractor: no stream found for {url}")
                    return None

                if stream_url.startswith('//'):
                    stream_url = 'https:' + stream_url
                if not stream_url.startswith(('http://', 'https://')):
                    logger.warning(f"Bunkr extractor produced non-http URL for {url}: {stream_url}")
                    return None

                if not title:
                    title = slug

                return {
                    "id": slug,
                    "title": title,
                    "description": f"Extracted from Bunkr ({url.split('/')[2] if '/' in url else 'bunkr'})",
                    "thumbnail": thumbnail,
                    "duration": 0,
                    "stream_url": stream_url,
                    "width": 0,
                    "height": 0,
                    "tags": [],
                    "uploader": "Bunkr",
                    "is_hls": False
                }

        except Exception as e:
            logger.error(f"Bunkr extraction error for {url}: {e}")
            return None

    async def heal(self, video_id: int, source_url: str, db_session) -> bool:
        """
        Special healing method for Bunkr links.
        If a direct link is dead, this re-extracts it and updates the DB.
        """
        logger.info(f"Healing Bunkr video {video_id} using source {source_url}")
        result = await self.extract(source_url)
        if result and result.get('stream_url'):
            from ..database import Video
            video = db_session.query(Video).get(video_id)
            if video:
                video.url = result['stream_url']
                video.last_checked = asyncio.get_event_loop().time() # Or datetime
                import datetime
                video.last_checked = datetime.datetime.now()
                db_session.commit()
                logger.info(f"Successfully healed Bunkr video {video_id}")
                return True
        return False
