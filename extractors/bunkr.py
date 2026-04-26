import asyncio
import json
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BunkrExtractor:
    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    async def extract_album(self, url: str):
        """
        Extracts clean JSON data from a Bunkr album page.
        Handles DDoS-Guard and dynamic DOM using Playwright.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()
            
            try:
                logger.info(f"Navigating to {url}")
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Check for "Checking your browser" or DDoS-Guard
                if "ddos-guard" in await page.content() or "Checking your browser" in await page.content():
                    logger.info("DDoS-Guard detected, waiting for bypass...")
                    await asyncio.sleep(5) # Wait for potential redirect or bypass
                
                # Execute JS to extract window.albumFiles
                files_data = await page.evaluate("() => window.albumFiles")
                
                if not files_data:
                    logger.warning("window.albumFiles not found in JS context. Attempting fallback extraction...")
                    # Fallback or error handling
                    return []

                logger.info(f"Successfully extracted {len(files_data)} files from album.")
                return files_data

            except Exception as e:
                logger.error(f"Error extracting Bunkr album: {e}")
                return []
            finally:
                await browser.close()

    async def extract_file(self, url: str):
        """
        Extracts direct download link for a specific Bunkr file.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # For single files, we check for multiple patterns
                download_link = await page.evaluate("""() => {
                    // 1. Direct video source
                    const video = document.querySelector('video source');
                    if (video && video.src) return video.src;
                    
                    // 2. Download button with attribute
                    const downloadBtn = document.querySelector('a[download], a.download-btn');
                    if (downloadBtn && downloadBtn.href) return downloadBtn.href;
                    
                    // 3. Any link containing media-files or bunkr cdn patterns
                    const allLinks = Array.from(document.querySelectorAll('a'));
                    const directLink = allLinks.find(a => 
                        a.href.includes('media-files') || 
                        a.href.includes('stream-files') || 
                        a.href.includes('bunkr') && (a.href.endsWith('.mp4') || a.href.endsWith('.mkv'))
                    );
                    if (directLink) return directLink.href;

                    // 4. Fallback: Search for text "Download"
                    const downloadTextLink = allLinks.find(a => a.textContent.toLowerCase().includes('download'));
                    if (downloadTextLink) return downloadTextLink.href;

                    return null;
                }""")
                
                # If it's a relative link, prepend protocol/host
                if download_link and download_link.startswith('//'):
                    download_link = "https:" + download_link
                
                return download_link

            except Exception as e:
                logger.error(f"Error extracting Bunkr file: {e}")
                return None
            finally:
                await browser.close()

if __name__ == "__main__":
    # Test script
    async def test():
        extractor = BunkrExtractor()
        # Replace with a real bunkr test URL if needed
        # test_url = "https://bunkr.si/a/XXXXXXX"
        # results = await extractor.extract_album(test_url)
        # print(json.dumps(results, indent=2))
        pass
    
    # asyncio.run(test())
