import logging
import re
import asyncio
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import aiohttp
import yt_dlp
from .base import VideoExtractor

logger = logging.getLogger(__name__)

class LeakPornerExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "LeakPorner"

    def can_handle(self, url: str) -> bool:
        return "leakporner.com" in url.lower()

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # Strategy 1: Try yt-dlp on the page directly
        result = await asyncio.to_thread(self._try_ytdlp, url)
        if result and result.get('stream_url'):
            logger.info(f"LeakPorner yt-dlp success: {url}")
            return result

        # Strategy 2: Parse page for embeds, then resolve them
        return await self._parse_and_resolve(url)

    def _try_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            ydl_opts = {
                'quiet': True, 'no_warnings': True, 'skip_download': True,
                'format': 'best[ext=mp4]/best[protocol*=m3u8]/best',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                return None
            stream_url = info.get('url')
            if not stream_url and info.get('formats'):
                fmts = sorted([f for f in info['formats'] if f.get('url')],
                               key=lambda f: f.get('height') or 0, reverse=True)
                if fmts:
                    stream_url = fmts[0]['url']
            if not stream_url:
                return None
            return {
                "id": info.get('id', ''),
                "title": info.get('title', ''),
                "description": info.get('description', ''),
                "thumbnail": info.get('thumbnail', ''),
                "duration": float(info.get('duration') or 0.0),
                "stream_url": stream_url,
                "width": int(info.get('width') or 0),
                "height": int(info.get('height') or 0),
                "tags": info.get('tags', []),
                "uploader": "LeakPorner",
                "is_hls": '.m3u8' in stream_url.lower(),
            }
        except Exception as e:
            logger.debug(f"LeakPorner yt-dlp failed: {e}")
            return None

    async def _parse_and_resolve(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://leakporner.com/'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()

            soup = BeautifulSoup(html, 'lxml')

            # Title
            title = (soup.find('meta', property='og:title') or {}).get('content', '')
            if not title:
                h1 = soup.find('h1', class_='entry-title')
                title = h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "LeakPorner Video")
            title = title.replace(' - LeakPorner', '').strip()

            # Thumbnail
            thumbnail = (soup.find('meta', property='og:image') or {}).get('content', '')

            # Duration from span.duration text
            dur_span = soup.find('span', class_='duration')
            duration = 0.0
            if dur_span:
                dur_text = dur_span.get_text(strip=True).replace('\xa0', '').strip()
                parts = [p for p in re.split(r'[:\s]+', dur_text) if p.isdigit()]
                if len(parts) == 3:
                    duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    duration = int(parts[0]) * 60 + int(parts[1])

            # Embed URLs
            embed_urls = []
            servideo = soup.find('div', class_='servideo')
            if servideo:
                for span in servideo.find_all('span', class_='change-video'):
                    e = span.get('data-embed')
                    if e:
                        embed_urls.append(e)
            if not embed_urls:
                embed_urls = re.findall(r'data-embed=["\']([^"\']+)["\']', html)

            video_id = url.rstrip('/').split('/')[-1] or url.rstrip('/').split('/')[-2]

            # Resolve embeds to direct stream
            stream_url = None
            async with aiohttp.ClientSession(headers=headers) as session:
                for embed_url in embed_urls[:4]:
                    stream_url = await self._resolve_embed(embed_url, session, url)
                    if stream_url:
                        logger.info(f"Resolved embed {embed_url} -> {stream_url[:60]}")
                        break

            # Fallback: try yt-dlp on embed URL
            if not stream_url and embed_urls:
                ytdlp_result = await asyncio.to_thread(self._try_ytdlp, embed_urls[0])
                if ytdlp_result:
                    stream_url = ytdlp_result.get('stream_url')
                    if not thumbnail and ytdlp_result.get('thumbnail'):
                        thumbnail = ytdlp_result['thumbnail']

            if not stream_url:
                stream_url = embed_urls[0] if embed_urls else url

            return {
                "id": video_id,
                "title": title,
                "description": title,
                "thumbnail": thumbnail,
                "duration": duration,
                "stream_url": stream_url,
                "width": 0, "height": 720,
                "tags": [],
                "uploader": "LeakPorner",
                "is_hls": '.m3u8' in (stream_url or '').lower(),
                "embed_urls": embed_urls,
            }
        except Exception as e:
            logger.error(f"LeakPorner extraction failed for {url}: {e}")
            return None

    async def _resolve_embed(self, embed_url: str, session: aiohttp.ClientSession, referer: str) -> Optional[str]:
        """Fetch embed page and find direct video URL inside."""
        try:
            # Special case for luluvids
            if 'luluvids.top' in embed_url:
                embed_url = embed_url.replace('/v/', '/e/').replace('luluvids.top', 'luluvids.com')

            async with session.get(embed_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': referer
            }, timeout=aiohttp.ClientTimeout(total=12), ssl=False) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()

            # Ordered patterns - most specific first
            patterns = [
                r'["\']?(https?://[^"\'>\s]+\.m3u8(?:\?[^"\'>\s]*)?)["\']?',
                r'["\']?(https?://[^"\'>\s]+\.mp4(?:\?[^"\'>\s]*)?)["\']?',
                r'file\s*:\s*["\']([^"\']+)["\']',
                r'"hls"\s*:\s*["\']([^"\']+)["\']',
                r'"src"\s*:\s*"(https?://[^"]+\.(?:m3u8|mp4)[^"]*)"',
                r'src=["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                r'sources\s*:\s*\[\s*\{\s*file\s*:\s*["\']([^"\']+)["\']',
            ]

            for pattern in patterns:
                for match in re.findall(pattern, html, re.IGNORECASE):
                    url_cand = match.strip().strip('"\'')
                    if not url_cand.startswith('http'):
                        if url_cand.startswith('//'):
                            url_cand = 'https:' + url_cand
                        else:
                            continue
                    if any(x in url_cand.lower() for x in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.js', '.css']):
                        continue
                    if '.m3u8' in url_cand.lower() or '.mp4' in url_cand.lower():
                        return url_cand
        except Exception as e:
            logger.debug(f"Embed resolve failed for {embed_url}: {e}")
        return None
