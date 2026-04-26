import requests
from bs4 import BeautifulSoup
import urllib.parse
import logging
import re
import asyncio
import aiohttp
from .websockets import manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import random
import os
import sys
from telethon.sync import TelegramClient
from telethon import functions, types
from dotenv import load_dotenv

# Ensure we can import from the root extractors package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from extractors.xenforo import XenForoExtractor

load_dotenv()

class ExternalSearchEngine:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
        }
        self.ssl_context = False
        self.tg_client = None
        self._init_telegram()

    def _init_telegram(self):
        try:
            api_id = os.getenv('TELEGRAM_API_ID')
            api_hash = os.getenv('TELEGRAM_API_HASH')
            if api_id and api_hash and os.path.exists('telegram_session.session'):
                # We use a non-async wrapper here or initialize in search
                # For aiohttp apps, we should init client inside async method
                pass
        except: pass

    def _merge_interleave_results(self, results):
        """Interleave results from different sources for variety."""
        source_mapped = {}
        for r in results:
            src = r['source']
            if src not in source_mapped:
                source_mapped[src] = []
            source_mapped[src].append(r)

        mixed_results = []
        seen_urls = set()
        max_len = max([len(v) for v in source_mapped.values()]) if source_mapped else 0

        for i in range(max_len):
            for src in sorted(source_mapped.keys()):
                if i < len(source_mapped[src]):
                    r = source_mapped[src][i]
                    if r['url'] not in seen_urls:
                        mixed_results.append(r)
                        seen_urls.add(r['url'])

        return mixed_results

    async def _run_single_discovery_source(self, query: str, key: str):
        """Run one canonical discovery source (key from source_catalog.DISCOVERY_SEARCH_SOURCE_KEYS)."""
        dispatch = {
            'bunkr': self.search_bunkr_async,
            'erome': self.search_erome_async,
            'gofile': self.search_gofile_async,
            'xvideos': self.search_xvideos_async,
            'kemono': self.search_kemono_async,
            'eporner': self.search_eporner_async,
            'pornhub': self.search_pornhub_async,
            'whoreshub': self.search_whoreshub_async,
            'porntrex': self.search_porntrex_async,
            'spankbang': self.search_spankbang_async,
            'xhamster': self.search_xhamster_async,
            'ixxx': self.search_ixxx_async,
        }
        fn = dispatch.get(key)
        if not fn:
            return []
        try:
            return await fn(query)
        except Exception as e:
            logger.error(f"Single-source search failed for {key}: {e}")
            return []

    async def search(self, query: str, source: str = None):
        """
        Main search method that aggregates results from multiple sources.
        If ``source`` is set to a recognized key, only that source is queried.
        Unrecognized non-empty tokens fall back to the full parallel search (legacy).
        """
        from .source_catalog import normalize_search_source_key

        results = []

        if source and str(source).strip():
            key = normalize_search_source_key(source)
            if key:
                return await self._run_single_discovery_source(query, key)

        # Parallel execution
        async def with_timeout(coro, seconds=15):
            try:
                return await asyncio.wait_for(coro, timeout=seconds)
            except Exception:
                return []

        tasks = [
            with_timeout(self.search_erome_async(query), 12),
            with_timeout(self.search_kemono_async(query), 12),
            with_timeout(self.search_xvideos_async(query), 12),
            with_timeout(self.search_pornhub_async(query), 12),
            with_timeout(self.search_eporner_async(query), 12),
            with_timeout(self.search_whoreshub_async(query), 15),
            with_timeout(self.search_porntrex_async(query), 15),
            with_timeout(self.search_bunkr_async(query), 20),
            with_timeout(self.search_gofile_async(query), 15),
            with_timeout(self.search_spankbang_async(query), 12),
            with_timeout(self.search_ixxx_async(query), 18),
        ]

        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in search_results:
            if isinstance(res, list):
                results.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Search error: {res}")

        return self._merge_interleave_results(results)

    async def search_sources(self, query: str, source_keys: list):
        """
        Search only the given canonical source keys (non-empty after validation).
        If the list is empty after validation, runs the full parallel search.
        """
        from .source_catalog import filter_valid_discovery_sources

        keys = filter_valid_discovery_sources(source_keys)
        if not keys:
            return await self.search(query, None)

        async def with_timeout(coro, seconds=15):
            try:
                return await asyncio.wait_for(coro, timeout=seconds)
            except Exception:
                return []

        timeout_map = {
            'erome': 12,
            'kemono': 12,
            'xvideos': 12,
            'pornhub': 12,
            'eporner': 12,
            'whoreshub': 15,
            'porntrex': 15,
            'bunkr': 20,
            'gofile': 15,
            'spankbang': 12,
            'xhamster': 15,
            'ixxx': 18,
        }

        tasks = [
            with_timeout(self._run_single_discovery_source(query, k), timeout_map.get(k, 15))
            for k in keys
        ]
        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for res in search_results:
            if isinstance(res, list):
                results.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Search error: {res}")

        return self._merge_interleave_results(results)

    async def search_bunkr_async(self, query: str):
        """
        Searches Bunkr across multiple domains with high efficiency.
        """
        results = []
        # Extensive list of Bunkr mirrors and related domains
        domains = [
            "bunkr.la", "bunkr.si", "bunkr.is", "bunkr-albums.io", 
            "bunkr.cr", "bunkr.black", "bunkr.su", "bunkr.pk",
            "bunkrr.su", "bunkr.ws"
        ]
        
        async def fetch_from_domain(domain):
            try:
                # Try multiple search paths commonly used by Bunkr mirrors
                search_paths = [
                    f"/s?search={urllib.parse.quote(query)}",
                    f"/search?q={urllib.parse.quote(query)}",
                    f"/search?search={urllib.parse.quote(query)}"
                ]
                
                html = ""
                async with aiohttp.ClientSession(headers=self.headers) as session:
                    for path in search_paths:
                        try:
                            search_url = f"https://{domain}{path}"
                            async with session.get(search_url, timeout=5, ssl=self.ssl_context) as resp:
                                if resp.status == 200:
                                    html = await resp.text()
                                    if "no results" not in html.lower() and len(html) > 1000:
                                        break
                        except:
                            continue
                
                if not html:
                    return []

                soup = BeautifulSoup(html, 'html.parser')
                # Improved selectors for various Bunkr versions
                items = soup.select('a[href*="/album/"], a[href*="/v/"], a[href*="/a/"], a[href*="/f/"]')
                
                domain_results = []
                for item in items:
                    href = item.get('href')
                    if not href or any(x in href for x in ['login', 'register', 'contact', 'tos']): 
                        continue
                    
                    full_url = href if href.startswith('http') else f"https://{domain}{href}"
                    
                    # Extract title with better hierarchy
                    title = item.get_text(strip=True)
                    if not title or len(title) < 4:
                        # Try to find title in adjacent elements (Bunkr often puts title in a p or div near the link)
                        parent = item.parent
                        if parent:
                            potential_title = parent.select_one('p, .title, .name, h1, h2, h3, h4, b, strong')
                            if potential_title:
                                title = potential_title.get_text(strip=True)
                    
                    # Clean up title
                    if not title or len(title) < 4:
                        title = full_url.split('/')[-1].replace('-', ' ').replace('_', ' ').title()
                    
                    # Filter out useless titles
                    if title.lower() in ['download', 'view', 'link', 'video', 'album']:
                        continue

                    # Attempt to find thumbnail if possible
                    thumbnail = None
                    img = item.select_one('img')
                    if img:
                        thumbnail = img.get('src') or img.get('data-src')
                        if thumbnail and not thumbnail.startswith('http'):
                            thumbnail = f"https://{domain}{thumbnail}"

                    domain_results.append({
                        'source': f'Bunkr ({domain})',
                        'title': title,
                        'url': full_url,
                        'description': f'Bunkr { "Album" if "/a/" in full_url or "/album/" in full_url else "File"}',
                        'thumbnail': thumbnail
                    })
                return domain_results
            except Exception as e:
                logger.debug(f"Error searching Bunkr domain {domain}: {e}")
                return []

        # Run multiple domains in parallel
        # Prioritize known active mirrors
        active_domains = [
            "bunkr.si", "bunkr.la", "bunkr.is", "bunkr-albums.io", "bunkr.cr", 
            "bunkr.black", "bunkrr.su", "bunkr.su", "bunkr.pk", "bunkr.ws", "bunkr.vc",
            "bunkr.ru", "bunkr.media", "bunkr.to"
        ]
        
        tasks = [fetch_from_domain(d) for d in active_domains]
        batch_results = await asyncio.gather(*tasks)
        
        for res in batch_results:
            results.extend(res)
            
        # Fallback to general search engines if no direct results found or to augment results
        # We increase pagination here to get closer to the user's "50 results" target
        if len(results) < 50:
            fallback_tasks = [
                self.search_via_duckduckgo_async(query, "bunkr.si", "Bunkr (Deep)"),
                self.search_via_duckduckgo_async(query, "bunkr-albums.io", "Bunkr (Deep)"),
                self.search_via_yahoo_async(query, "bunkr.si", "Bunkr (Deep)"),
                self.search_via_yahoo_async(query, "bunkr.la", "Bunkr (Deep)"),
                self.search_via_duckduckgo_async(query, "bunkrr.su", "Bunkr (Deep)"),
                self.search_simpcity_async(query) # Add SimpCity for Bunkr links
            ]
            fallbacks = await asyncio.gather(*fallback_tasks)
            for f_res in fallbacks:
                results.extend(f_res)
            
        # Deduplicate results by URL
        seen = set()
        final_results = []
        for r in results:
            if r['url'] not in seen:
                # Basic validation: ensure it's a bunkr/bunkrr link or from simpcity
                is_valid = any(x in r['url'].lower() for x in ['bunkr', 'bunkrr', 'simpcity'])
                if is_valid:
                    final_results.append(r)
                    seen.add(r['url'])
                
        return final_results[:100] # Cap at 100 for performance

    async def search_gofile_async(self, query: str):
        """
        Searches Gofile links. Since Gofile doesn't have a public search,
        we use indexed search engines to find gofile.io links.
        """
        return await self.search_via_yahoo_async(query, "gofile.io", "Gofile")

    async def search_pixeldrain_async(self, query: str):
        """
        Searches Pixeldrain links via Yahoo.
        """
        return await self.search_via_yahoo_async(query, "pixeldrain.com", "Pixeldrain")

    async def search_telegram_async(self, query: str):
        """
        Searches Telegram channels via DuckDuckGo using site:t.me operator.
        """
        results = []
        try:
            search_query = f"site:t.me {query}"
            url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(search_query)}"
            
            headers = self.headers.copy()
            headers['Accept'] = 'text/html'
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"Telegram search via DDG failed: {resp.status}")
                        return []
                    html = await resp.text()

            if "no results" in html.lower() or len(html) < 500:
                logger.info(f"No Telegram results for query: {query}")
                return []

            soup = BeautifulSoup(html, 'html.parser')
            links = soup.find_all('a', href=True)
            
            for link in links[:30]:  # Check more links for Telegram
                href = link.get('href', '')
                if not href or href.startswith('#'):
                    continue
                
                # Extract actual URL from DDG redirect
                actual_url = href
                if 'uddg=' in href:
                    try:
                        actual_url = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                    except:
                        pass
                
                # Only include t.me links
                if 't.me/' not in actual_url:
                    continue
                
                title = link.get_text(strip=True)
                if not title or len(title) < 3:
                    # Try to get title from parent
                    parent = link.find_parent('tr') or link.find_parent('div')
                    if parent:
                        title_elem = parent.find('span') or parent.find('b')
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                
                if not title:
                    # Extract channel name from URL
                    title = actual_url.split('t.me/')[-1].split('/')[0]
                
                results.append({
                    'source': 'Telegram',
                    'title': title,
                    'url': actual_url,
                    'description': f"Telegram channel/post"
                })
                
        except Exception as e:
            logger.error(f"Error searching Telegram via DDG: {e}")

        # --- TELETHON LAYER (Deep Search) ---
        # If configured, we merge real results from his account
        try:
            api_id = os.getenv('TELEGRAM_API_ID')
            api_hash = os.getenv('TELEGRAM_API_HASH')
            
            if api_id and api_hash and os.path.exists('telegram_session.session'):
                tele_results = await self.search_telegram_telethon(query, api_id, api_hash)
                results.extend(tele_results)
        except Exception as e:
            logger.error(f"Telethon error: {e}")

        return results
    async def search_telegram_telethon(self, query: str, api_id, api_hash):
        results = []
        try:
            # Connect only when needed
            # Use a slightly different session name or ensure we don't conflict if multiple searches run? 
            # Telethon handles this usually.
            await manager.log(f"Telegram: Connecting to session...", "working")
            # Use new session file to avoid locks from crashed processes
            async with TelegramClient('telegram_session_v3', int(api_id), api_hash) as client:
                await manager.log(f"Telegram: Authenticated. Searching global messages...", "working")
                # Search GLOBAL messages (content within your channels/groups)
                # Filter specifically for VIDEOS to match user intent
                from telethon.tl.types import InputMessagesFilterVideo
                
                count = 0
                processed = 0
                # Use list aggregation instead of direct async for if stability is an issue, 
                # but direct iteration is standard. 
                # Ensure we handle the loop correctly.
                async for message in client.search_global(query, filter=InputMessagesFilterVideo, limit=40):
                    processed += 1
                    try:
                        chat = await message.get_chat()
                        chat_title = getattr(chat, 'title', getattr(chat, 'username', 'Unknown Source'))
                        
                        # Generate Link
                        if getattr(chat, 'username', None):
                            # Public: t.me/username/123
                            link = f"https://t.me/{chat.username}/{message.id}"
                        else:
                            # Private: t.me/c/123456789/123
                            # Normalize ID: Telethon returns -100123... for channels, we need 123...
                            chat_id_str = str(chat.id).replace('-100', '')
                            link = f"https://t.me/c/{chat_id_str}/{message.id}"
                        
                        # Determine Title (Caption or Filename)
                        caption = message.message or ""
                        filename = "Telegram Video"
                        
                        # Check attributes for constraints
                        duration = 0
                        size = 0
                        
                        if message.document:
                            size = message.document.size
                            for attr in message.document.attributes:
                                if hasattr(attr, 'file_name') and attr.file_name:
                                    filename = attr.file_name
                                if hasattr(attr, 'duration'):
                                    duration = attr.duration

                        # RELAXED FILTER (For Debugging):
                        # Show anything > 1 min OR > 50MB
                        # Let's see if we get ANY results first
                        if duration < 60 and size < (50 * 1024 * 1024):
                            continue

                        display_title = caption if len(caption) > 5 else filename
                        if len(display_title) > 80: display_title = display_title[:80] + "..."
                        
                        # Format size string
                        size_mb = f"{size / (1024*1024):.1f} MB"
                        duration_str = f"{duration // 60}:{duration % 60:02d}"

                        results.append({
                            'source': f'Telegram ({chat_title})',
                            'title': display_title,
                            'url': link,
                            'description': f"Video | {duration_str} | {size_mb} | Found in {chat_title}",
                            'thumbnail': None 
                        })
                        count += 1
                    except Exception as loop_e:
                        logger.error(f"Error processing tg message: {loop_e}")
                        continue
                
                await manager.log(f"Telegram: Scanned {processed} msgs, Found {count} valid videos.", "success")

        except Exception as e:
            logger.error(f"Telethon crash: {e}")
        return results

    async def search_simpcity_async(self, query: str):
        """
        Robust search for SimpCity using XenForoExtractor with auto-login.
        """
        try:
            scout = XenForoExtractor("https://simpcity.su")
            
            # Load credentials from environment
            simpcity_email = os.getenv('SIMPCITY_EMAIL')
            simpcity_password = os.getenv('SIMPCITY_PASSWORD')
            
            if simpcity_email and simpcity_password:
                scout.set_credentials(simpcity_email, simpcity_password)
                logger.info("SimpCity credentials loaded from environment")
            
            # We wrap the blocking search in an executor
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, scout.search, query)
            
            # Label as SimpCity
            for r in results:
                r['source'] = 'SimpCity'
                r['description'] = 'Robust extraction via XenForoExtractor'
            
            return results
        except Exception as e:
            logger.error(f"SimpCity robust search failed: {e}")
            return await self.search_via_yahoo_async(query, "simpcity.su", "SimpCity (Fallback)")

    async def search_smg_async(self, query: str):
        """
        Robust search for SocialMediaGirls using XenForoExtractor.
        """
        try:
            scout = XenForoExtractor("https://socialmediagirls.com")
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, scout.search, query)
            
            for r in results:
                r['source'] = 'SMG'
                r['description'] = 'Robust extraction via XenForoExtractor'
            
            return results
        except Exception as e:
            logger.error(f"SMG robust search failed: {e}")
            return await self.search_via_yahoo_async(query, "socialmediagirls.com", "SMG (Fallback)")

    async def search_f95zone_async(self, query: str):
        """
        Searches F95Zone via DuckDuckGo (Cloudflare protected, so direct scraping is difficult).
        """
        return await self.search_via_yahoo_async(query, "f95zone.to", "F95Zone")

    async def search_leakedmodels_async(self, query: str):
        """
        Searches LeakedModels.com via DuckDuckGo.
        """
        return await self.search_via_yahoo_async(query, "leakedmodels.com", "LeakedModels")

    async def search_via_yahoo_async(self, query: str, site: str, source_label: str):
        """
        Searches a specific site using Yahoo Search (more reliable than DDG for some queries).
        """
        results = []
        try:
            clean_query = query.replace(f"site:{site}", "").strip()
            if not clean_query:
                clean_query = site.split('.')[0]
            
            search_query = f"site:{site} {clean_query}"
            url = f"https://search.yahoo.com/search?p={urllib.parse.quote(search_query)}"
            
            headers = {
                'User-Agent': self.headers['User-Agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/', # Pretend we come from Google
            }
            
            # Small random delay to avoid rate limiting
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"Yahoo Search failed: {resp.status} for {site}")
                        # Fallback to DDG lite if Yahoo fails
                        return await self.search_via_ddg_lite_async(query, site, source_label)
                    html = await resp.text()

            if "did not match any documents" in html.lower() or len(html) < 1000:
                return []

            soup = BeautifulSoup(html, 'html.parser')
            # Yahoo results are in div.algo or h3
            items = soup.select('div.algo') or soup.select('div.dd.algo')
            
            for item in items[:20]:
                link_elem = item.find('a')
                if not link_elem: continue
                
                actual_url = link_elem.get('href', '')
                # Yahoo redirects are complex, but usually the clean URL is in the href or RU= param
                if 'RU=' in actual_url:
                    try:
                        actual_url = urllib.parse.unquote(actual_url.split('RU=')[1].split('/')[0])
                    except: pass
                
                # Check for direct link
                if not actual_url.startswith('http'): continue
                if 'search.yahoo.com' in actual_url and 'RU=' not in actual_url: continue
                
                if site not in actual_url and site.split('.')[0] not in actual_url: continue

                title_elem = link_elem
                title = title_elem.get_text(strip=True)
                
                desc_elem = item.select_one('.compText, .st')
                description = desc_elem.get_text(strip=True) if desc_elem else f"Found on {source_label}"
                
                results.append({
                    'source': source_label,
                    'title': title,
                    'url': actual_url,
                    'description': description[:200]
                })
        except Exception as e:
            logger.error(f"Error searching {source_label} via Yahoo: {e}")
        return results

    async def search_via_ddg_lite_async(self, query: str, site: str, source_label: str):
        """
        Original DDG Lite search as fallback.
        """
        results = []
        try:
            search_query = f"site:{site} {query}"
            url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(search_query)}"
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, timeout=10, ssl=self.ssl_context) as resp:
                    if resp.status != 200: return []
                    html = await resp.text()
            soup = BeautifulSoup(html, 'html.parser')
            links = soup.find_all('a', class_='result-link')
            for link in links[:15]:
                href = link.get('href', '')
                actual_url = href
                if 'uddg=' in href: actual_url = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
                if site not in actual_url: continue
                results.append({
                    'source': source_label, 'title': link.get_text(strip=True), 'url': actual_url,
                    'description': f"Found on {source_label}"
                })
        except: pass
        return results


    async def search_reddit_async(self, query: str):
        """
        Searches Reddit using JSON API
        """
        results = []
        try:
            url = f"https://www.reddit.com/search.json?q={urllib.parse.quote(query)}&limit=50"
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, timeout=10, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()

            for child in data.get('data', {}).get('children', []):
                post = child.get('data', {})
                title = post.get('title')
                url = post.get('url')
                permalink = f"https://reddit.com{post.get('permalink')}"
                
                target_domains = ['gofile.io', 'pixeldrain.com', 'bunkr', 'mega.nz', 'simpcity', 'socialmediagirls']
                
                source_label = 'Reddit'
                target_url = url
                
                found_domain = next((d for d in target_domains if d in url), None)
                if found_domain:
                     source_label = f"{found_domain.capitalize()} (via Reddit)"
                else:
                    target_url = permalink
                
                results.append({
                    'source': source_label,
                    'title': title,
                    'url': target_url,
                    'description': f"Reddit post: {post.get('subreddit_name_prefixed')}"
                })

        except Exception as e:
            logger.error(f"Error searching Reddit: {e}")
            
        return results

    async def search_erome_async(self, query: str):
        """
        Searches Erome.com profiles and albums directly with robust retry and fallback.
        """
        results = []
        
        # Try multiple Erome mirrors/domains
        domains = ["www.erome.com", "erome.com", "v.erome.com"]
        
        for domain in domains:
            try:
                url = f"https://{domain}/search?q={urllib.parse.quote(query)}"
                
                headers = self.headers.copy()
                headers['Referer'] = f'https://{domain}/'
                
                # Retry logic with exponential backoff
                for attempt in range(2):
                    try:
                        async with aiohttp.ClientSession(headers=headers) as session:
                            async with session.get(url, timeout=20, ssl=self.ssl_context) as resp:
                                if resp.status == 503:
                                    logger.warning(f"Erome {domain} returned 503, attempt {attempt+1}/2")
                                    if attempt == 0:
                                        await asyncio.sleep(2)  # Wait before retry
                                        continue
                                    else:
                                        break  # Try next domain
                                
                                if resp.status != 200:
                                    logger.debug(f"Erome {domain} returned {resp.status}")
                                    break
                                
                                html = await resp.text()
                        
                                soup = BeautifulSoup(html, 'html.parser')
                                
                                # Find album cards
                                albums = soup.select('#album-list .album') or soup.select('.album')
                                
                                async def fetch_album_details(album_data):
                                    """Optional: Fetch album page to get total duration if not visible."""
                                    try:
                                        async with session.get(album_data['url'], timeout=10) as a_resp:
                                            if a_resp.status == 200:
                                                a_html = await a_resp.text()
                                                a_soup = BeautifulSoup(a_html, 'html.parser')
                                                
                                                # Look for duration patterns in videos on the page
                                                # Erome video wrappers often have a data-duration or similar
                                                durations = []
                                                # Or check for duration labels in the UI
                                                for d_label in a_soup.select('.video-duration, .duration'):
                                                    d_txt = d_label.get_text(strip=True)
                                                    if d_txt:
                                                        # Convert MM:SS to seconds
                                                        try:
                                                            p = d_txt.split(':')
                                                            if len(p) == 2: durations.append(int(p[0])*60 + int(p[1]))
                                                            elif len(p) == 3: durations.append(int(p[0])*3600 + int(p[1])*60 + int(p[2]))
                                                        except: pass
                                                
                                                if durations:
                                                    album_data['duration'] = sum(durations)
                                                    
                                                # Quality detection - check if any 4k/HD mentions on page or titles
                                                if "4k" in a_html.lower(): album_data['quality'] = '4K'
                                                elif "1080" in a_html.lower() or "hd" in a_html.lower(): album_data['quality'] = 'HD'
                                    except: pass
                                    return album_data

                                raw_results = []
                                for album in albums[:20]:
                                    link_elem = album.find('a', href=True)
                                    if not link_elem: continue
                                        
                                    href = link_elem.get('href', '')
                                    if not href: continue
                                    
                                    full_url = href if href.startswith('http') else f"https://{domain}{href}"
                                    
                                    title_elem = album.select_one('.album-title') or album.find('span', class_='title')
                                    title = title_elem.get_text(strip=True) if title_elem else "Erome Album"
                                    
                                    img_elem = album.find('img')
                                    thumbnail = None
                                    if img_elem:
                                        thumbnail = img_elem.get('data-src') or img_elem.get('data-original') or img_elem.get('src')
                                    
                                    if not thumbnail or 'pixel' in thumbnail: 
                                         thumbnail = f"https://{domain}/assets/img/logo_small.png"
                
                                    # Get counts
                                    video_count = 0
                                    photo_count = 0
                                    
                                    # Erome info icons
                                    info_spans = album.select('.album-info span')
                                    for span in info_spans:
                                        txt = span.get_text(strip=True)
                                        if span.find('i', class_='fa-video'):
                                            try: video_count = int(re.sub(r'\D', '', txt))
                                            except: video_count = 1
                                        elif span.find('i', class_='fa-image'):
                                            try: photo_count = int(re.sub(r'\D', '', txt))
                                            except: photo_count = 0
                                    
                                    # Fallback count detection
                                    if video_count == 0 and album.find('i', class_='fa-video'):
                                        video_count = 1

                                    is_album = video_count > 1 or photo_count > 0
                                    desc_parts = []
                                    if video_count > 0: desc_parts.append(f"{video_count} videos")
                                    if photo_count > 0: desc_parts.append(f"{photo_count} photos")
                                    
                                    res = {
                                        'source': 'Erome',
                                        'title': title,
                                        'url': full_url,
                                        'description': f"Erome {'Album' if is_album else 'Video'} ({', '.join(desc_parts)})",
                                        'thumbnail': thumbnail,
                                        'video_count': video_count,
                                        'photo_count': photo_count,
                                        'duration': 0,
                                        'quality': 'HD' 
                                    }
                                    
                                    # Basic quality detection from title
                                    if "4k" in title.lower(): res['quality'] = '4K'
                                    elif "1080" in title.lower(): res['quality'] = '1080p'
                                    
                                    raw_results.append(res)
                                
                                # Deep search for durations (Parallel)
                                if raw_results:
                                    results = await asyncio.gather(*[fetch_album_details(r) for r in raw_results])
                                    return results
                                break 
                    except asyncio.TimeoutError:
                        logger.warning(f"Erome {domain} timeout, attempt {attempt+1}/2")
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        break
            except Exception as e:
                logger.debug(f"Erome {domain} failed: {e}")
                continue
        
        # If all domains failed, return empty
        if not results:
            logger.error("All Erome domains failed or returned no results")
        return results

    async def search_coomer_async(self, query: str):
        """
        Searches Coomer.party (OnlyFans, Fansly, etc. archive) with robust retry.
        """
        results = []
        
        # Try multiple Coomer domains
        domains = ["coomer.cr", "coomer.su", "coomer.party"]
        
        for domain in domains:
            try:
                url = f"https://{domain}/posts?q={urllib.parse.quote(query)}"
                
                headers = self.headers.copy()
                
                # Retry logic
                for attempt in range(2):
                    try:
                        async with aiohttp.ClientSession(headers=headers) as session:
                            async with session.get(url, timeout=20, ssl=self.ssl_context) as resp:
                                if resp.status == 503:
                                    logger.warning(f"Coomer {domain} returned 503, attempt {attempt+1}/2")
                                    if attempt == 0:
                                        await asyncio.sleep(2)
                                        continue
                                    else:
                                        break
                                
                                if resp.status != 200:
                                    logger.debug(f"Coomer {domain} returned {resp.status}")
                                    break
                                
                                html = await resp.text()
                        
                                soup = BeautifulSoup(html, 'html.parser')
                                posts = soup.find_all('article', class_='post-card') or soup.find_all('div', class_='post-card')
                                
                                for post in posts[:20]:
                                    link_elem = post.find('a', href=True)
                                    if not link_elem:
                                        continue
                                    
                                    href = link_elem.get('href', '')
                                    full_url = href if href.startswith('http') else f"https://{domain}{href}"
                                    
                                    # Get title/description
                                    title_elem = post.find('header') or post.find('h2') or post.find('span')
                                    title = title_elem.get_text(strip=True) if title_elem else "Coomer Post"
                                    
                                    img_elem = post.find('img')
                                    thumbnail = img_elem.get('src', '') if img_elem else None
                                    if thumbnail and not thumbnail.startswith('http'):
                                        thumbnail = f"https://{domain}{thumbnail}"
                                    
                                    results.append({
                                        'source': 'Coomer.party',
                                        'title': title,
                                        'url': full_url,
                                        'description': f"Found on Coomer",
                                        'thumbnail': thumbnail
                                    })
                                
                                # If we got results, return them
                                if results:
                                    return results
                                break
                    except asyncio.TimeoutError:
                        logger.warning(f"Coomer {domain} timeout, attempt {attempt+1}/2")
                        if attempt == 0:
                            await asyncio.sleep(1)
                            continue
                        break
            except Exception as e:
                logger.debug(f"Coomer {domain} failed: {e}")
                continue
        
        # Fallback to Yahoo if all domains failed
        if not results:
            logger.info("All Coomer domains failed, falling back to Yahoo search")
            return await self.search_via_yahoo_async(query, "coomer.cr", "Coomer (via Yahoo)")
        return results

    async def search_kemono_async(self, query: str):
        """
        Searches Kemono.party (Patreon, SubscribeStar, etc. archive)
        """
        results = []
        try:
            # Try to find the creator by searching
            search_url = f"https://kemono.cr/posts?q={urllib.parse.quote(query)}"
            
            headers = self.headers.copy()
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"Kemono search failed: {resp.status}")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            
            # Find post cards
            posts = soup.find_all('article', class_='post-card')[:20]
            
            for post in posts:
                # Get post link
                link_elem = post.find('a', class_='post-card__link') or post.find('a', href=True)
                if not link_elem:
                    continue
                    
                href = link_elem.get('href', '')
                if not href:
                    continue
                
                full_url = href if href.startswith('http') else f"https://kemono.cr{href}"
                
                # Get title
                title_elem = post.find('header') or post.find('h2') or post.find('span', class_='post-card__header')
                title = title_elem.get_text(strip=True) if title_elem else "Kemono Post"
                
                # Get creator name
                creator_elem = post.find('a', class_='post-card__user-name') or post.find('span', class_='user-name')
                creator = creator_elem.get_text(strip=True) if creator_elem else "Unknown"
                
                # Get service (Patreon, etc.)
                service_elem = post.find('span', class_='post-card__service') or post.find('img', class_='service-icon')
                service = service_elem.get('alt', 'Patreon') if service_elem else 'Patreon'
                
                # Get thumbnail
                img_elem = post.find('img')
                thumbnail = img_elem.get('src', '') if img_elem else None
                if thumbnail and not thumbnail.startswith('http'):
                    thumbnail = f"https://kemono.su{thumbnail}"
                
                results.append({
                    'source': f'Kemono.party ({service})',
                    'title': title[:100],
                    'url': full_url,
                    'description': f"By {creator} on {service}",
                    'thumbnail': thumbnail
                })
                
        except Exception as e:
            logger.error(f"Error searching Kemono.party: {e}")
        return results

    async def search_xvideos_async(self, query: str):
        """
        Searches XVideos.com directly
        """
        results = []
        try:
            # XVideos search URL
            search_url = f"https://www.xvideos.com/?k={urllib.parse.quote(query)}"
            
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.xvideos.com/'
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"XVideos search failed: {resp.status}")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            
            # Find video thumbnails
            videos = soup.find_all('div', class_='thumb-block')[:20]
            
            for video in videos:
                # Get link
                link_elem = video.find('a', href=True)
                if not link_elem:
                    continue
                    
                href = link_elem.get('href', '')
                if not href:
                    continue
                
                full_url = href if href.startswith('http') else f"https://www.xvideos.com{href}"
                
                # Get title
                title_elem = video.find('p', class_='title') or link_elem
                title = title_elem.get('title', '') or title_elem.get_text(strip=True)
                
                # Get thumbnail
                img_elem = video.find('img')
                thumbnail = img_elem.get('data-src') or img_elem.get('src', '') if img_elem else None
                
                # Get duration
                duration_elem = video.find('span', class_='duration')
                duration = duration_elem.get_text(strip=True) if duration_elem else ""

                # Get quality
                quality = ""
                hd_mark = video.find('span', class_='video-hd-mark')
                if hd_mark:
                    quality = hd_mark.get_text(strip=True)
                
                results.append({
                    'source': 'XVideos',
                    'title': title[:100],
                    'url': full_url,
                    'description': f"Duration: {duration}" if duration else "XVideos video",
                    'thumbnail': thumbnail,
                    'quality': quality
                })
                
        except Exception as e:
            logger.error(f"Error searching XVideos: {e}")
        return results

    async def search_spankbang_async(self, query: str):
        """
        Searches SpankBang.com directly via mirrors.
        """
        results = []
        # Try mirrors if main is blocked
        domains = ["spankbang.com", "spankbang.party", "la.spankbang.com"]
        
        for domain in domains:
            try:
                search_url = f"https://{domain}/s/{urllib.parse.quote(query)}/"
                
                headers = self.headers.copy()
                headers.update({
                    'Referer': f'https://{domain}/',
                    'Host': domain,
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive'
                })
                
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(search_url, timeout=10, ssl=self.ssl_context) as resp:
                        if resp.status != 200:
                            logger.debug(f"SpankBang mirror {domain} failed: {resp.status}")
                            continue
                        html = await resp.text()

                soup = BeautifulSoup(html, 'html.parser')
                # Find video items
                videos = soup.find_all('div', class_='video-item')[:20]
                
                if not videos:
                    # Alternative selector
                    videos = soup.select('.video-list .video-item')

                for video in videos:
                    # Get link
                    link_elem = video.find('a', href=True)
                    if not link_elem:
                        continue
                        
                    href = link_elem.get('href', '')
                    if not href:
                        continue
                    
                    full_url = href if href.startswith('http') else f"https://{domain}{href}"
                    
                    # Get title
                    title = link_elem.get('title', '') or link_elem.get_text(strip=True)
                    
                    # Get thumbnail
                    img_elem = video.find('img')
                    thumbnail = img_elem.get('data-src') or img_elem.get('src', '') if img_elem else None
                    if thumbnail and thumbnail.startswith('//'):
                        thumbnail = f"https:{thumbnail}"
                    
                    # Get info
                    info_elem = video.find('span', class_='i')
                    duration = info_elem.get_text(strip=True) if info_elem else ""

                    # Get quality
                    quality = ""
                    q_elem = video.find('span', class_='q')
                    if q_elem:
                        quality = q_elem.get_text(strip=True)
                    
                    results.append({
                        'source': 'SpankBang',
                        'title': title[:100],
                        'url': full_url,
                        'description': f"Duration: {duration}" if duration else "SpankBang video",
                        'thumbnail': thumbnail,
                        'quality': quality
                    })
                
                if results:
                    break # Success with this domain
            except Exception as e:
                logger.debug(f"Error searching SpankBang on {domain}: {e}")
                continue
        
        if not results:
            logger.info("SpankBang direct failed or blocked, falling back to Yahoo")
            return await self.search_via_yahoo_async(query, "spankbang.com", "SpankBang (via Yahoo)")
                
        return results

    async def search_pornhub_async(self, query: str):
        """
        Searches Pornhub.com directly
        """
        results = []
        try:
            # Pornhub search URL
            search_url = f"https://www.pornhub.com/video/search?search={urllib.parse.quote(query)}"
            
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.pornhub.com/'
            headers['Cookie'] = 'accessAgeDisclaimerPH=1; accessPH=1;'  # Age verification
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"Pornhub search failed: {resp.status}")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            
            # Find video items
            videos = soup.find_all('li', class_='pcVideoListItem')[:20]
            
            # Fallback selector
            if not videos:
                videos = soup.find_all('div', class_='phitem')[:20]
            
            for video in videos:
                # Get link
                link_elem = video.find('a', href=True)
                if not link_elem:
                    continue
                    
                href = link_elem.get('href', '')
                if not href or 'javascript:' in href:
                    continue
                
                full_url = href if href.startswith('http') else f"https://www.pornhub.com{href}"
                
                # Get title
                title_elem = video.find('span', class_='title') or video.find('a', {'title': True})
                title = title_elem.get('title', '') if title_elem else link_elem.get('title', '')
                if not title:
                    title = link_elem.get_text(strip=True)
                
                # Get thumbnail
                img_elem = video.find('img')
                thumbnail = img_elem.get('data-src') or img_elem.get('data-thumb_url') or img_elem.get('src', '') if img_elem else None
                
                # Get duration
                duration_elem = video.find('var', class_='duration')
                duration = duration_elem.get_text(strip=True) if duration_elem else ""

                # Get quality
                quality = ""
                hd_elem = video.find('span', class_='hd-thumbnail')
                if hd_elem:
                    quality = "HD"
                    if "4k" in hd_elem.get_text(strip=True).lower():
                        quality = "4K"
                
                results.append({
                    'source': 'Pornhub',
                    'title': title[:100],
                    'url': full_url,
                    'description': f"Duration: {duration}" if duration else "Pornhub video",
                    'thumbnail': thumbnail,
                    'quality': quality
                })
                
        except Exception as e:
            logger.error(f"Error searching Pornhub: {e}")
        return results


    async def search_eporner_async(self, query: str):
        """
        Searches Eporner via API (wrapped from services).
        """
        results = []
        try:
             # Lazy import to avoid circular dependency issues
            from .services import fetch_eporner_videos
            loop = asyncio.get_event_loop()
            videos = await loop.run_in_executor(None, fetch_eporner_videos, query)
            
            for v in videos:
                results.append({
                    'source': 'Eporner',
                    'title': v['title'],
                    'url': v['url'], 
                    'duration': v.get('duration'),
                    'quality': v.get('quality', ''),
                    'description': f"Found on Eporner",
                    'thumbnail': v['thumbnail']
                })
        except Exception as e:
            logger.error(f"Eporner search failed: {e}")
        return results

    async def search_whoreshub_async(self, query: str):
        results = []
        try:
            from .whoreshub_discovery import scrape_whoreshub_discovery
            loop = asyncio.get_event_loop()
            videos = await loop.run_in_executor(
                None, lambda: scrape_whoreshub_discovery(keyword=query, tag="", min_quality=720, min_duration=0, pages=1, upload_type="all", auto_skip_low_quality=False)
            )
            for v in videos:
                results.append({
                    'source': 'WhoresHub',
                    'title': v.get('title', '')[:100],
                    'url': v.get('url', ''),
                    'description': f"Duration: {v.get('duration', '')}",
                    'thumbnail': v.get('thumbnail'),
                    'quality': str(v.get('quality', ''))
                })
        except Exception as e:
            logger.error(f"WhoresHub search failed: {e}")
        return results

    async def search_porntrex_async(self, query: str):
        results = []
        try:
            from .porntrex_discovery import scrape_porntrex_discovery
            loop = asyncio.get_event_loop()
            videos = await loop.run_in_executor(
                None, lambda: scrape_porntrex_discovery(keyword=query, min_quality=720, pages=1, category="", upload_type="all", auto_skip_low_quality=False)
            )
            for v in videos:
                results.append({
                    'source': 'PornTrex',
                    'title': v.get('title', '')[:100],
                    'url': v.get('url', ''),
                    'description': f"Duration: {v.get('duration', '')}",
                    'thumbnail': v.get('thumbnail'),
                    'quality': str(v.get('quality', ''))
                })
        except Exception as e:
            logger.error(f"PornTrex search failed: {e}")
        return results

    async def search_xhamster_async(self, query: str):
        results = []
        try:
            search_url = f"https://xhamster.com/search/{urllib.parse.quote(query)}"
            headers = self.headers.copy()
            headers['Referer'] = 'https://xhamster.com/'

            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        logger.error(f"xHamster search failed: {resp.status}")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            video_items = soup.select('div.video-thumb')[:20] or soup.select('div[class*="thumb-list"] > div')[:20]

            for item in video_items:
                link = item.find('a', href=True)
                if not link:
                    continue
                href = link.get('href', '')
                full_url = href if href.startswith('http') else f"https://xhamster.com{href}"
                title = link.get('title', '') or link.get_text(strip=True)
                img = item.find('img')
                thumbnail = img.get('data-src') or img.get('src') if img else None
                dur_elem = item.find(class_=lambda c: c and 'duration' in c)
                duration = dur_elem.get_text(strip=True) if dur_elem else ''
                results.append({
                    'source': 'xHamster',
                    'title': title[:100],
                    'url': full_url,
                    'description': f"Duration: {duration}" if duration else "xHamster video",
                    'thumbnail': thumbnail,
                    'quality': ''
                })
        except Exception as e:
            logger.error(f"xHamster search failed: {e}")
        return results

    async def search_ixxx_async(self, query: str):
        """
        Search ixxx.com via listing scrape (first page(s) only by default for latency).
        """
        results = []
        try:
            from .extractors.ixxx import IxxxExtractor

            q = (query or "").strip()
            if not q:
                return []

            search_url = f"https://www.ixxx.com/search/?query={urllib.parse.quote(q)}"
            max_pages = int(os.getenv("IXXX_SEARCH_MAX_PAGES", "2"))
            ext = IxxxExtractor()
            rows = await ext.extract_listing(search_url, max_pages=max_pages)

            for row in rows:
                results.append(
                    {
                        "source": "iXXX",
                        "title": (row.get("title") or "")[:200],
                        "url": row.get("url") or "",
                        "description": "Found on iXXX",
                        "thumbnail": row.get("thumbnail"),
                        "duration": row.get("duration") or 0,
                        "width": row.get("width") or 0,
                        "height": row.get("height") or 0,
                        "quality": "",
                    }
                )
        except Exception as e:
            logger.error(f"iXXX search failed: {e}")
        return results

    async def search_via_yahoo_async(self, query: str, site: str, source_name: str):
        """
        Uses Yahoo Search to find results for a specific site.
        Very useful for sites with poor or no internal search.
        """
        results = []
        try:
            # Yahoo Search URL with site: operator
            search_query = f"site:{site} {query}"
            search_url = f"https://search.yahoo.com/search?p={urllib.parse.quote(search_query)}"
            
            headers = self.headers.copy()
            headers.update({
                'Referer': 'https://search.yahoo.com/',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            })
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=15, ssl=self.ssl_context) as resp:
                    if resp.status != 200:
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            # Yahoo search results are typically in <div> with class "dd algo algo-sr" or similar
            items = soup.select('.algo-sr, .dd.algo')
            
            for item in items:
                link_tag = item.select_one('a[href*="https://"]')
                if not link_tag: continue
                
                url = link_tag.get('href')
                
                # Clean Yahoo redirect URLs
                if 'r.search.yahoo.com' in url:
                    try:
                        parsed_url = urllib.parse.urlparse(url)
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        if 'RU' in query_params:
                            url = query_params['RU'][0]
                        elif '/RV=' in url:
                            # Try regex if RU is not standard
                            match = re.search(r'RU=([^/]+)', url)
                            if match:
                                url = urllib.parse.unquote(match.group(1))
                    except: pass
                
                # Only include results for the target site or variants
                is_bunkr = any(x in url.lower() for x in ['bunkr', 'bunkrr'])
                if site not in url.lower() and not (is_bunkr and 'bunkr' in site):
                    continue
                
                title_tag = item.select_one('h3')
                title = title_tag.get_text(strip=True) if title_tag else url.split('/')[-1]
                
                # Skip search engine result pages or meta links
                if any(x in url.lower() for x in ['search?', 'results?', 'google.com', 'yahoo.com', 'duckduckgo']):
                    continue

                desc_tag = item.select_one('.compText, .st')
                description = desc_tag.get_text(strip=True) if desc_tag else f"Result from {site}"

                results.append({
                    'source': source_name,
                    'title': title,
                    'url': url,
                    'description': description
                })
        except Exception as e:
            logger.error(f"Yahoo fallback search failed for {site}: {e}")
            
        return results

    async def search_via_duckduckgo_async(self, query: str, site: str, source_name: str):
        """
        Fallback search via DuckDuckGo (HTML version).
        """
        results = []
        try:
            search_query = f"site:{site} {query}"
            # DDG HTML version is easier to scrape, kp=-1 disables Safe Search
            search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query)}&kp=-1"
            
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(search_url, timeout=10, ssl=self.ssl_context) as resp:
                    if resp.status != 200: return []
                    html = await resp.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            items = soup.select('.result')
            
            for item in items:
                link = item.select_one('.result__a')
                if not link: continue
                
                url = link.get('href')
                
                # Clean DDG redirect URLs
                if 'uddg=' in url:
                    try:
                        url = urllib.parse.unquote(url.split('uddg=')[1].split('&')[0])
                    except: pass
                
                is_bunkr = any(x in url.lower() for x in ['bunkr', 'bunkrr'])
                if site not in url.lower() and not (is_bunkr and 'bunkr' in site):
                    continue
                
                title = link.get_text(strip=True)
                snippet = item.select_one('.result__snippet')
                description = snippet.get_text(strip=True) if snippet else ""
                
                # Skip junk
                if any(x in url.lower() for x in ['search?', 'results?', 'google.com', 'yahoo.com', 'duckduckgo']):
                    continue

                results.append({
                    'source': source_name,
                    'title': title,
                    'url': url,
                    'description': description
                })
        except Exception as e:
            logger.error(f"DDG fallback search failed for {site}: {e}")
        return results

    async def search_simpcity_async(self, query: str):
        """
        Searches SimpCity (XenForo) for threads mentioning the query.
        SimpCity is a major source of Bunkr and other cyberdrop links.
        """
        results = []
        try:
            # We use the public search if available, or just a site-specific search
            return await self.search_via_duckduckgo_async(query, "simpcity.su", "SimpCity")
        except Exception as e:
            logger.error(f"SimpCity search failed: {e}")
        return results
