import asyncio
import logging
import re
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class XHamsterExtractor:
    def __init__(self):
        # Using desktop UA to simulate real user
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def parse_cookie_file(self, path):
        cookies = []
        if not path: return []
        try:
            with open(path, 'r') as f:
                for line in f:
                    if not line.strip() or line.startswith('#'): continue
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        cookies.append({
                            'name': parts[5],
                            'value': parts[6].strip(),
                            'domain': parts[0],
                            'path': parts[2],
                            'expires': int(parts[4]) if parts[4] and int(parts[4]) > 0 else -1,
                            'httpOnly': False,
                            'secure': parts[3] == 'TRUE'
                        })
            logger.info(f"Loaded {len(cookies)} cookies from {path}")
            return cookies
        except Exception as e:
            logger.error(f"Cookie parse error: {e}")
            return []

    async def extract_metadata(self, url: str):
        """
        Extracts high-quality metadata from xHamster using Playwright "Nuclear Option".
        Intercepts network requests to find the best HLS/MP4 streams.
        """
        cookies = self.parse_cookie_file('xhamster.cookies.txt')
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox', 
                    '--disable-setuid-sandbox', 
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--window-size=1920,1080',
                    '--start-maximized'
                ]
            )
            
            # Use high-res viewport with extra headers
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1'
                }
            )
            
            if cookies:
                await context.add_cookies(cookies)
                
            page = await context.new_page()
            
            # DATA HOLDER
            found_streams = []

            # 1. NETWORK INTERCEPTION
            # We listen for m3u8 or mp4 requests that look like video streams
            page.on("request", lambda request: found_streams.append({
                'url': request.url,
                'type': 'hls' if '.m3u8' in request.url else 'mp4'
            }) if ('.m3u8' in request.url or '.mp4' in request.url) and 'cdn' in request.url else None)

            try:
                logger.info(f"Navigating to {url} with Playwright (Nuclear Mode)...")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Check for "Age Verification" or "Disclaimer" buttons
                # xHamster often has a "I am 18 or older" button
                try:
                    await page.click('button.av-btn-yes, .buttons-container .btn, [data-role="accept-disclaimer"]', timeout=3000)
                    logger.info("Clicked Age Verification/Disclaimer")
                except: pass

                # Wait for stable state
                await page.wait_for_load_state("networkidle")
                
                # Scroll to trigger lazy loading
                await page.evaluate("window.scrollTo(0, 500)")
                await asyncio.sleep(2)
                
                # Debug screenshot
                await page.screenshot(path="xhamster_debug.png")
                logger.info(f"Page Title: {await page.title()}")

                # 2. JS EVALUATION (INITIAL DATA)
                # xHamster often stores video data in window.initials or specifically structured JSON in scripts
                page_data = await page.evaluate("""() => {
                    const meta = {
                        title: document.title,
                        thumb: null,
                        duration: 0,
                        streams: []
                    };
                    
                    // Title
                    const h1 = document.querySelector('h1');
                    if (h1) meta.title = h1.innerText;

                    // Thumb
                    const poster = document.querySelector('video');
                    if (poster) meta.thumb = poster.poster;

                    // Try to extract from window object if available (often xplayer or similar)
                    if (window.xplayer_data) {
                        return window.xplayer_data; // This would be jackpot
                    }

                    return meta;
                }""")
                
                # 3. DEEP PAGE SCAN (REGEX)
                content = await page.content()
                
                # Extract Title Clean
                title_match = re.search(r'<h1[^>]*>(.*?)</h1>', content)
                final_title = title_match.group(1).strip() if title_match else page_data.get('title', 'Unknown Title')
                
                # Extract Duration
                # xHamster duration often in LD-JSON
                duration = 0
                dur_match = re.search(r'"duration":\s*"PT(\d+)M(\d+)S"', content)
                if dur_match:
                    duration = int(dur_match.group(1)) * 60 + int(dur_match.group(2))
                
                # Intelligent Stream Selection
                stream_url = None
                quality_type = "Unknown"
                
                # A. Check intercepted streams (Highest Priority if HLS is found)
                hls_streams = [s['url'] for s in found_streams if s['type'] == 'hls']
                mp4_streams = [s['url'] for s in found_streams if s['type'] == 'mp4']
                
                if hls_streams:
                    # Prefer the one that looks like a master playlist
                    master = next((s for s in hls_streams if 'master' in s), hls_streams[0])
                    stream_url = master
                    quality_type = "HLS-Network"
                
                # B. Regex Search in Page Source (if network failed)
                if not stream_url:
                    # Look for m3u8 in valid JSON or variable
                    m3u8_matches = re.findall(r'https?://[^"\']+\.m3u8[^"\']*', content)
                    if m3u8_matches:
                        # Filter out garbage
                        valid_m3u8 = [m for m in m3u8_matches if 'cdn' in m]
                        if valid_m3u8:
                            stream_url = valid_m3u8[0]
                            quality_type = "HLS-Regex"

                # C. MP4 Fallback
                if not stream_url and mp4_streams:
                    # Find longest link (heuristic for better quality sometimes)
                    try:
                        stream_url = max(mp4_streams, key=len)
                        quality_type = "MP4-Network"
                    except: pass

                safe_url = stream_url[:50] if stream_url else "None"
                logger.info(f"xHamster extraction success: {quality_type} - {safe_url}...")
                
                return {
                    "source": "xhamster",
                    "title": final_title,
                    "stream_url": stream_url,
                    "thumbnail_url": page_data.get('thumb') if page_data else None,
                    "duration": duration,
                    "quality_source": quality_type,
                    "found": bool(stream_url)
                }

            except Exception as e:
                logger.error(f"Playwright xHamster Error: {e}")
                return None
            finally:
                await browser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    async def test():
        xh = XHamsterExtractor()
        print("Testing homepage video...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://xhamster.com")
            
            # PRO-TIP: Handle Disclaimer on Homepage
            # Aggressive JS click to bypass overlays
            await page.evaluate("""() => {
                const btns = document.querySelectorAll('[data-role="accept-disclaimer"], .buttons-container .btn, button');
                btns.forEach(b => {
                    if(b.innerText.includes('Enter') || b.innerText.includes('ENTER') || b.innerText.includes('18')) b.click();
                });
                // Remove cookie modal if blocking
                const cookie = document.querySelector('[data-role="cookies-modal"]');
                if(cookie) cookie.remove();
            }""")
            await asyncio.sleep(1)
            
            # Click first video thumb
            await page.click('.video-thumb__image-container')
            current_url = page.url
            print(f"Picked URL: {current_url}")
            await browser.close()
            
            res = await xh.extract_metadata(current_url)
            print(f"Result: {res}")
    
    asyncio.run(test())
