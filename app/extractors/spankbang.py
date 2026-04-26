import yt_dlp
import logging
import asyncio
import re
from .base import VideoExtractor
from typing import Optional, Dict, Any

class SpankBangExtractor(VideoExtractor):
    @property
    def name(self) -> str:
        return "SpankBang"

    def can_handle(self, url: str) -> bool:
        return "spankbang.com" in url

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        # 1. Try yt-dlp first
        meta = self._extract_ytdlp(url)
        if meta and (meta.get('height') or 0) >= 1080:
             return meta
             
        # 2. Use Playwright (Integrated)
        try:
            logging.info(f"Using Integrated Playwright Extractor for SpankBang: {url}")
            pw_res = await self._extract_playwright(url)
            
            if pw_res and pw_res.get('found'):
                is_hls = 'hls' in (pw_res.get('quality_source') or '').lower() or '.m3u8' in pw_res['stream_url']
                return {
                    "id": meta.get('id') if meta else None,
                    "title": pw_res['title'],
                    "description": "",
                    "thumbnail": pw_res.get('thumbnail_url'),
                    "duration": pw_res.get('duration') or (meta.get('duration') if meta else 0),
                    "stream_url": pw_res['stream_url'],
                    "width": 1920 if is_hls else 0,
                    "height": 1080 if is_hls else (meta.get('height') if meta else 0),
                    "tags": pw_res.get('tags') or (meta.get('tags') if meta else []),
                    "uploader": "",
                    "is_hls": is_hls
                }
        except Exception as e:
            logging.error(f"Playwright SpankBang fallback failed: {e}")

        return meta

    async def _extract_playwright(self, url: str):
        """
        Embeds the Playwright extraction logic directly to avoid import issues.
        """
        from playwright.async_api import async_playwright
        
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={'width': 1920, 'height': 1080}
            )
            
            page = await context.new_page()
            
            try:
                m3u8_urls = []
                page.on("response", lambda response: m3u8_urls.append(response.url) if ".m3u8" in response.url.lower() else None)

                logging.info(f"Navigating to {url} with Playwright...")
                # Use domcontentloaded to be faster, then wait specific selector
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # Wait for video player or reasonable time
                try:
                    await page.wait_for_selector('video, .video-content', timeout=10000)
                except: pass

                # Check for "Confirm Age"
                try:
                    confirm_btn = await page.query_selector('button:has-text("Confirm Age"), .confirm-age, #confirm-age')
                    if confirm_btn and await confirm_btn.is_visible():
                        await confirm_btn.click()
                        await asyncio.sleep(1)
                except: pass

                content = await page.content()
                
                # Extract Title
                title = await page.title()
                try:
                    h1 = await page.query_selector('h1')
                    if h1: title = await h1.inner_text()
                except: pass
                
                # Extract Thumbnail
                thumb = None
                try:
                    og_image = await page.query_selector('meta[property="og:image"]')
                    if og_image: thumb = await og_image.get_attribute('content')
                except: pass
                
                # Stream URL derivation
                stream_url = None
                quality = "Unknown"
                
                # PRIORITY 1: JS Variable (Most reliable for main video)
                # SpankBang usually puts it in 'stream_url' or 'video_url'
                js_stream_match = re.search(r'var\s+stream_url\s*=\s*["\']([^"\']+)["\'];', content)
                if js_stream_match:
                    stream_url = js_stream_match.group(1)
                    quality = "HLS-JS-Var"
                
                if not stream_url:
                    # PRIORITY 2: Network Intercepted M3U8 (Filtered)
                    # We try to pick the longest one or ensure it's not an ad
                    # Ads often have unique tokens or domains, but 'sb-cd.com' is usually content.
                    valid_m3u8s = [u for u in m3u8_urls if "preview" not in u.lower() and "ad" not in u.lower()]
                    if valid_m3u8s:
                        # Pick the last one? often the main video loads last after ads
                        # Or stick to first non-preview?
                        # Let's try the one containing 'master' or matches 'sb-cd'
                        master_m3u8 = next((u for u in valid_m3u8s if "master.m3u8" in u), None)
                        stream_url = master_m3u8 if master_m3u8 else valid_m3u8s[-1] 
                        quality = "HLS-Network"
                
                if not stream_url:
                    # PRIORITY 3: Deep Regex Fallback
                    match_hls = re.search(r'["\'](https?://[^"\']+?\.m3u8[^"\']*?)["\']', content)
                    if match_hls:
                        stream_url = match_hls.group(1)
                        quality = "HLS-Regex"
                    else:
                        for q in ['4k', '1080p', '720p', '480p', '360p']:
                            m = re.search(fr'var\s+video_url_{q}\s*=\s*["\'](.*?)["\'];', content)
                            if m:
                                stream_url = m.group(1)
                                quality = f"MP4-{q}"
                                break
                                
                # Extract Tags and Duration
                tags = []
                duration = 0
                try:
                     tags = await page.evaluate("""() => {
                        const links = document.querySelectorAll('a[href*="/tag/"], .video-tags a');
                        return Array.from(links).map(a => a.innerText.trim()).filter(t => t.length > 0);
                    }""")
                     
                     duration_text = await page.evaluate("""() => {
                        const el = document.querySelector('.duration, .video-duration, span.d');
                        return el ? el.innerText : null;
                    }""")
                     if duration_text:
                        parts = duration_text.split(':')
                        if len(parts) == 3: duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        elif len(parts) == 2: duration = int(parts[0]) * 60 + int(parts[1])
                except: pass

                return {
                    "title": title.strip(),
                    "stream_url": stream_url,
                    "thumbnail_url": thumb,
                    "quality_source": quality,
                    "duration": duration,
                    "tags": tags,
                    "found": bool(stream_url)
                }

            except Exception as e:
                logging.error(f"Playwright SpankBang Error: {e}")
                return None
            finally:
                await browser.close()


    def _extract_ytdlp(self, url: str) -> Optional[Dict[str, Any]]:
        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ydl_opts = {
            'quiet': True, 'skip_download': True, 'extract_flat': False,
            'format': 'bestvideo+bestaudio/best', 
            'ignoreerrors': True, 'no_warnings': True,
            'user_agent': user_agent,
            'http_headers': {'User-Agent': user_agent, 'Referer': 'https://spankbang.com/'}
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info: return None

                formats = info.get('formats', [])
                valid_formats = []
                for f in formats:
                    if not f.get('url'): continue
                    height = f.get('height') or 0
                    is_hls = '.m3u8' in f['url'] or 'hls' in f.get('protocol', '').lower()
                    if is_hls and height == 0: height = 1080
                    valid_formats.append({'url': f['url'], 'height': height, 'is_hls': is_hls})

                valid_formats.sort(key=lambda x: (x['is_hls'], x['height']), reverse=True)
                best = valid_formats[0] if valid_formats else {'url': info.get('url'), 'height': 0, 'is_hls': False}

                return {
                    "id": info.get('id'),
                    "title": info.get('title'),
                    "description": info.get('description'),
                    "thumbnail": info.get('thumbnail'),
                    "duration": info.get('duration'),
                    "stream_url": best['url'],
                    "width": info.get('width') or 0,
                    "height": best['height'] or info.get('height') or 0,
                    "tags": info.get('tags', []),
                    "uploader": info.get('uploader'),
                    "is_hls": best.get('is_hls', False)
                }
        except Exception:
            return None
