import asyncio
import logging
import re
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class XVideosExtractor:
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def parse_cookie_file(self, path):
        cookies = []
        if not path:
            return []
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
        Extracts high-quality metadata from XVideos using Playwright.
        Returns a dict with title, hls_url, duration, thumbnail, etc.
        """
        import os
        email = os.getenv("XVIDEOS_EMAIL")
        password = os.getenv("XVIDEOS_PASSWORD")
        
        cookie_path = 'xvideos.cookies.txt'
        cookies = self.parse_cookie_file(cookie_path)
        
        async with async_playwright() as p:
            # Launch with arguments to minimize detection/headless flags
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='en-US'
            )
            
            if cookies:
                await context.add_cookies(cookies)

            page = await context.new_page()

            # Handle Login if needed
            if email and password:
                # Check if we are logged in by going to a page that requires login or shows profile
                await page.goto("https://www.xvideos.com/myprofile", wait_until="networkidle")
                if "login" in page.url or "Account Login" in await page.title():
                    logger.info("Not logged in. Performing login...")
                    await page.goto("https://www.xvideos.com/account/login")
                    await page.fill('input[name="signin-form[login]"]', email)
                    await page.fill('input[name="signin-form[password]"]', password)
                    await page.click('button#signin-submit')
                    await page.wait_for_load_state("networkidle")
                    
                    # Save cookies for future use
                    new_cookies = await context.cookies()
                    # Convert to netscape format for yt-dlp compatibility if needed, 
                    # but here we just save them for this extractor.
                    # We'll stick to our simple parse_cookie_file for now or just trust context.
                    # Actually, let's just use them in the current session.
                    logger.info("Login successful (hopefully).")

            try:
                # Setup network listener
                m3u8_urls = []
                page.on("response", lambda response: m3u8_urls.append(response.url) if ".m3u8" in response.url else None)

                logger.info(f"Navigating to {url} with Playwright...")
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Handle Interstitial / Disclaimer
                if "disclaimer" in url or (await page.query_selector('#disclaimer_background')):
                     logger.info("Disclaimer detected, clicking Enter...")
                     try:
                         await page.click('#disclaimer_background a', timeout=5000)
                         await page.wait_for_load_state("networkidle")
                     except: 
                         # Try pure JS click
                         await page.evaluate("document.querySelector('#disclaimer_background a').click()")
                         await asyncio.sleep(3)

                # Try to click PLAY to trigger HLS request
                try:
                    logger.info("Attempting to click Play...")
                    # Common selectors for xvideos player play button
                    await page.click('#html5video_base .play-btn, .big-play-btn, #html5video .play-btn', timeout=3000)
                    await asyncio.sleep(3) # Wait for requests
                except:
                    logger.info("Play button not found or already playing.")

                # Take a debug screenshot
                await page.screenshot(path="xvideos_debug.png")
                logger.info("Saved xvideos_debug.png")

                # Wait for potential player load
                try: await page.wait_for_selector('div#video-player-bg', timeout=5000)
                except: pass

                content = await page.content()
                
                # Check captured network requests
                if m3u8_urls:
                    logger.info(f"Found {len(m3u8_urls)} HLS URLs via network interception")
                
                # Extract metadata
                metadata = await page.evaluate("""() => {
                    const meta = {
                        title: document.title,
                        thumb: null
                    };
                    const h1 = document.querySelector('h2.page-title') || document.querySelector('.video-title h1 strong');
                    if (h1) meta.title = h1.innerText;
                    return meta;
                }""")

                # Regex extraction
                hls_match = re.search(r"html5player\.setVideoHLS\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
                high_match = re.search(r"html5player\.setVideoUrlHigh\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
                low_match = re.search(r"html5player\.setVideoUrlLow\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
                thumb_match = re.search(r"html5player\.setThumbUrl169\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
                
                title_match = re.search(r"html5player\.setVideoTitle\s*\(\s*['\"]([^'\"]+)['\"]\s*\);", content)
                final_title = title_match.group(1) if title_match else metadata['title']
                
                stream_url = None
                quality = "Unknown"
                
                # Normalize URL for network interception check if needed, 
                # but captured URLs will have the actual domain used.
                
                # Priority 1: Network intercepted HLS (Refers to actual playback)
                if m3u8_urls:
                    stream_url = m3u8_urls[0]
                    quality = "HLS-Network"
                # Priority 2: JS Variable HLS
                elif hls_match:
                    stream_url = hls_match.group(1)
                    quality = "HLS-JS"
                # Priority 3: MP4 High
                elif high_match:
                    stream_url = high_match.group(1)
                    quality = "MP4-High"
                # Priority 4: Deep Search
                elif not stream_url:
                    deep_hls = re.search(r"['\"](https?://[^'\"]+?\.m3u8[^'\"]*?)['\"]", content)
                    if deep_hls:
                        stream_url = deep_hls.group(1)
                        quality = "HLS-Deep"
                # Priority 5: MP4 Low (Fallback)
                if not stream_url and low_match:
                    stream_url = low_match.group(1)
                    quality = "MP4-Low"

                return {
                    "title": final_title,
                    "stream_url": stream_url,
                    "thumbnail_url": thumb_match.group(1) if thumb_match else None,
                    "quality_source": quality,
                    "found": bool(stream_url)
                }

            except Exception as e:
                logger.error(f"Playwright XVideos Error: {e}")
                return None
            finally:
                await browser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        xv = XVideosExtractor()
        
        # Test 1: The problematic URL
        url = "https://www.xvideos.com/video.kdfhhmbeee9/teenfidelity_kelly_oliveira_rocks_her_body_for_big_dick"
        print(f"Testing problematic URL: {url}")
        res = await xv.extract_metadata(url)
        print(f"Result: {res}")
        
        # Test 2: Random value from homepage
        print("\nTesting homepage video...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://www.xvideos.com")
            # Click first video thumb
            await page.click('.thumb-block .thumb a')
            current_url = page.url
            print(f"Picked URL: {current_url}")
            res2 = await xv.extract_metadata(current_url)
            print(f"Result: {res2}")
            await browser.close()
    
    asyncio.run(test())
