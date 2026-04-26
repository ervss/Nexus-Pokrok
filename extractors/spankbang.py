import asyncio
import logging
import re
import json
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class SpankBangExtractor:
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    async def extract_metadata(self, url: str):
        """
        Extracts high-quality metadata from SpankBang using Playwright.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080}
            )
            
            page = await context.new_page()
            
            try:
                # Intercept m3u8 requests
                m3u8_urls = []
                page.on("response", lambda response: m3u8_urls.append(response.url) if ".m3u8" in response.url.lower() else None)

                logger.info(f"Navigating to {url} with Playwright...")
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Check for "Confirm Age" button
                confirm_btn = await page.query_selector('button:has-text("Confirm Age"), .confirm-age, #confirm-age')
                if confirm_btn:
                    logger.info("Confirm Age button found, clicking...")
                    await confirm_btn.click()
                    await page.wait_for_load_state("networkidle")

                # Try to trigger playback if no m3u8 found yet
                if not m3u8_urls:
                    logger.info("No HLS found yet, trying to click play...")
                    try:
                        play_btn = await page.query_selector('.play_btn, #video_player_container, .vjs-big-play-button')
                        if play_btn:
                            await play_btn.click(timeout=5000)
                            await asyncio.sleep(5)
                    except:
                        logger.info("Play button click failed or timed out.")

                content = await page.content()
                
                # Extract Title
                title = await page.title()
                h1 = await page.query_selector('h1')
                if h1:
                    title = await h1.inner_text()
                
                # Extract Thumbnail
                thumb = None
                og_image = await page.query_selector('meta[property="og:image"]')
                if og_image:
                    thumb = await og_image.get_attribute('content')
                
                # Stream URL derivation
                stream_url = None
                quality = "Unknown"
                
                if m3u8_urls:
                    # Filter out non-master playlists if possible or pick the first one
                    stream_url = m3u8_urls[0]
                    quality = "HLS-Network"
                else:
                    # Try regex on page content
                    match_hls = re.search(r'["\'](https?://[^"\']+?\.m3u8[^"\']*?)["\']', content)
                    if match_hls:
                        stream_url = match_hls.group(1)
                        quality = "HLS-Regex"
                    else:
                        # Search for qualities in JS variables
                        for q in ['4k', '1080p', '720p', '480p', '360p']:
                            m = re.search(fr'var\s+video_url_{q}\s*=\s*["\'](.*?)["\'];', content)
                            if m:
                                stream_url = m.group(1)
                                quality = f"MP4-{q}"
                                break

                # Extract Tags
                tags = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href*="/tag/"], .video-tags a');
                    return Array.from(links).map(a => a.innerText.trim()).filter(t => t.length > 0);
                }""")

                # Duration calculation (if available in DOM)
                duration = 0
                duration_text = await page.evaluate("""() => {
                    const el = document.querySelector('.duration, .video-duration, span.d');
                    return el ? el.innerText : null;
                }""")
                if duration_text:
                    # Parse HH:MM:SS or MM:SS
                    parts = duration_text.split(':')
                    if len(parts) == 3:
                        duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration = int(parts[0]) * 60 + int(parts[1])
                
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
                logger.error(f"Playwright SpankBang Error: {e}")
                return None
            finally:
                await browser.close()

    async def extract_playlist(self, url: str):
        """
        Extracts all video URLs from a SpankBang playlist page.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080}
            )
            
            page = await context.new_page()
            
            try:
                base_url = url.split('?')[0].rstrip('/')
                all_videos = []
                
                # We limit to first 5 pages for safety, but usually it's enough
                for page_num in range(1, 6):
                    current_url = f"{base_url}/?page={page_num}" if page_num > 1 else base_url
                    logger.info(f"Navigating to playlist page {page_num}: {current_url}")
                    
                    await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
                    
                    # Wait for items to appear or a bit of time
                    try:
                        await page.wait_for_selector('.video-item, .video-list, a.thumb', timeout=10000)
                    except:
                        pass
                    
                    # Handle Confirmation if it blocks view
                    try:
                        confirm_btn = await page.query_selector('button:has-text("Confirm Age"), .confirm-age, #confirm-age')
                        if confirm_btn and await confirm_btn.is_visible():
                            await confirm_btn.click()
                            await asyncio.sleep(2)
                    except: pass

                    # Scroll a bit to trigger lazy load if any
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                    await asyncio.sleep(1)
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1)

                    # Extract links - more inclusive
                    links = await page.evaluate("""() => {
                        const items = document.querySelectorAll('.video-item a, a.thumb, a.n');
                        const results = [];
                        items.forEach(a => {
                            const href = a.href;
                            // Look for patterns like /user-vid/playlist/name or /video/id
                            if (href && (href.includes('/playlist/') || href.includes('/video/'))) {
                                // Exclude pagination or current playlist root if possible
                                if (!href.includes('?page=') && !href.endsWith('/playlist/')) {
                                     results.push(href);
                                }
                            }
                        });
                        return results;
                    }""")
                    
                    if not links:
                        # Emergency fallback - every link that looks like a video link
                        links = await page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('a'))
                                .map(a => a.href)
                                .filter(h => h && h.match(/\/[a-z0-9]+-[a-z0-9]+\/playlist\//));
                        }""")

                    if not links:
                        logger.warning(f"No links found on SpankBang playlist page {page_num}")
                        break
                        
                    # Clean and add
                    cleaned = [l.split('?')[0].split('#')[0] for l in links]
                    all_videos.extend(cleaned)
                    
                    # Deduplicate within the page to see if we got new ones
                    page_unique = list(set(cleaned))
                    logger.info(f"Page {page_num} found {len(page_unique)} links")
                    
                    # Check for Next button
                    next_btn = await page.query_selector('a.next, .pagination-next a, [class*="next"] a')
                    if not next_btn:
                        break
                
                final_list = list(dict.fromkeys(all_videos))
                return final_list

            except Exception as e:
                logger.error(f"Playwright SpankBang Playlist Error: {e}")
                return []
            finally:
                await browser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    async def test():
        sb = SpankBangExtractor()
        # Test Video
        url = "https://spankbang.com/c2ozv-pji44l/playlist/rus"
        res = await sb.extract_metadata(url)
        print("Video Meta:")
        print(json.dumps(res, indent=2))
        
        # Test Playlist
        playlist_url = "https://spankbang.com/c2ozv/playlist/rus/"
        print("\nExpanding Playlist...")
        links = await sb.extract_playlist(playlist_url)
        print(f"Found {len(links)} links")
        for l in links[:5]:
            print(f" - {l}")
    asyncio.run(test())
