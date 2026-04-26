import requests
from bs4 import BeautifulSoup
import os
import logging
import re
import base64
from urllib.parse import urlparse, parse_qs, unquote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class XenForoExtractor:
    def __init__(self, base_url, cookie_dict=None):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if cookie_dict:
            domain = self.base_url.split('//')[-1]
            for name, value in cookie_dict.items():
                self.session.cookies.set(name, value, domain=domain)
                
                # Simpcity compatibility for older naming
                if "simpcity" in domain:
                    if name == "xf_session":
                        self.session.cookies.set("ogaddgmetaprof_session", value, domain=domain)
                    elif name == "xf_user":
                        self.session.cookies.set("ogaddgmetaprof_user", value, domain=domain)
        
        self.credentials = None # Store as (username, password) if needed

    def set_credentials(self, username, password):
        self.credentials = (username, password)

    def is_logged_in(self):
        """Checks if currently logged in by visiting the home page and looking for user bar."""
        try:
            resp = self.session.get(self.base_url, timeout=10)
            return "Log out" in resp.text or "account" in resp.text.lower()
        except:
            return False

    def login(self):
        """Attempts to login using stored credentials."""
        if not self.credentials:
            logger.warning(f"No credentials set for {self.base_url}")
            return False
            
        username, password = self.credentials
        login_url = f"{self.base_url}/login/login" # Standard XenForo login POST action
        
        # 1. Get CSRF token
        try:
            resp = self.session.get(f"{self.base_url}/login/", timeout=10)
            soup = BeautifulSoup(resp.text, 'html.parser')
            t_token = soup.select_one('input[name="_xfToken"]')
            csrf_token = t_token['value'] if t_token else None
            
            if not csrf_token:
                logger.error(f"Could not find CSRF token for {self.base_url}")
                return False
                
            data = {
                "login": username,
                "password": password,
                "remember": 1,
                "_xfToken": csrf_token,
                "return_url": "/"
            }
            
            # 2. POST login
            headers = {"Referer": f"{self.base_url}/login/"}
            resp = self.session.post(login_url, data=data, headers=headers, timeout=15)
            
            if self.is_logged_in():
                logger.info(f"Successfully logged in to {self.base_url}")
                # Update cookies in the session automatically
                return True
            else:
                logger.warning(f"Login failed for {self.base_url}. Potential captcha or wrong credentials.")
                return False
        except Exception as e:
            logger.error(f"Login exception for {self.base_url}: {e}")
            return False

    def search(self, query):
        """
        Executes a search on the XenForo forum.
        """
        search_url = f"{self.base_url}/search/search"
        # Prepare search payload
        payload = {
            "keywords": query,
            "c[title_only]": 0,  # Search in full content, not just titles
            "o": "relevance"     # Order by relevance
        }
        
        try:
            logger.info(f"Searching {self.base_url} for '{query}'")
            response = self.session.get(search_url, params=payload, timeout=30)
            
            # If we get 403 or find no results, try to login and retry
            if response.status_code == 403 or (not self._parse_search_results(response.text) and self.credentials):
                logger.info(f"Search for '{query}' failed or blocked. Attempting auto-login...")
                if self.login():
                    response = self.session.get(search_url, params=payload, timeout=30)
            
            response.raise_for_status()
            return self._parse_search_results(response.text)
        except Exception as e:
            logger.error(f"Error searching forum {self.base_url}: {e}")
            return []

    def _parse_search_results(self, html):
        """
        Parses search result threads. Supports multiple XenForo structures.
        """
        soup = BeautifulSoup(html, 'html.parser')
        threads = []
        
        # Priority 1: standard XenForo list items
        items = soup.select('li.block-row.block-row--separated')
        if not items:
            # Priority 2: content rows (sometimes used in different views)
            items = soup.select('div.contentRow-main')
            
        for result in items:
            # Try multiple selectors for the title and link
            title_elem = result.select_one('h3.contentRow-title a') or \
                         result.select_one('a[href*="/threads/"]') or \
                         result.select_one('h3 a')
            
            if title_elem and 'href' in title_elem.attrs:
                href = title_elem['href']
                if not href.startswith('http'):
                    href = self.base_url + ('' if href.startswith('/') else '/') + href
                
                threads.append({
                    "title": title_elem.text.strip(),
                    "url": href,
                    "source": "Simpcity" if "simpcity" in self.base_url else "SMG"
                })
        
        return threads

    def extract_links_from_thread(self, thread_url, max_pages=3):
        """
        Scans a thread for supported media links, following pagination.
        Returns list of dicts with link metadata including thumbnails from posts.
        """
        all_links = []
        current_url = thread_url
        pages_visited = 0
        
        while current_url and pages_visited < max_pages:
            try:
                logger.info(f"Extracting links from page {pages_visited+1}: {current_url}")
                response = self.session.get(current_url, timeout=30)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find all posts (messages)
                posts = soup.select('.message-body, .bbWrapper')
                
                for post in posts:
                    # Extract all images in this post to use as previews
                    post_images = []
                    for img in post.select('img'):
                        img_src = img.get('src') or img.get('data-src')
                        if img_src and not any(x in img_src.lower() for x in ['emoji', 'smilie', 'icon', 'avatar']):
                            if img_src.startswith('//'): img_src = 'https:' + img_src
                            elif img_src.startswith('/'): img_src = self.base_url + img_src
                            post_images.append(img_src)
                    
                    # Process all links in the post
                    links = post.find_all('a', href=True)
                    img_idx = 0
                    
                    for link_elem in links:
                        href = link_elem['href']
                        
                        # Handle XenForo confirmation redirects (Common on SocialMediaGirls)
                        if "link-confirmation" in href:
                            try:
                                parsed = urlparse(href)
                                qs = parse_qs(parsed.query)
                                if 'url' in qs:
                                    encoded_url = qs['url'][0]
                                    # Base64 padding if needed
                                    missing_padding = len(encoded_url) % 4
                                    if missing_padding:
                                        encoded_url += '=' * (4 - missing_padding)
                                    href = base64.b64decode(encoded_url).decode('utf-8', errors='ignore')
                            except Exception as e:
                                logger.debug(f"Failed to decode confirmation link: {e}")

                        link_text = link_elem.get_text(strip=True)
                        
                        platform = None
                        link_type = "unknown"
                        file_id = None
                        
                        # Identify platform and ID
                        if "bunkr" in href:
                            platform = "bunkr"
                            # Support .site, .ac, .la, .ru, etc.
                            v_match = re.search(r'/v/([a-zA-Z0-9-]+)', href)
                            a_match = re.search(r'/(?:a|f)/([a-zA-Z0-9-]+)', href)
                            if v_match:
                                file_id = v_match.group(1)
                                link_type = "video"
                                href = f"https://bunkr.site/v/{file_id}"
                            elif a_match:
                                file_id = a_match.group(1)
                                link_type = "album"
                                href = f"https://bunkr.site/a/{file_id}"
                        elif "gofile.io/d/" in href:
                            platform = "gofile"
                            link_type = "archive"
                            file_id = href.split('/')[-1]
                        elif "mega.nz" in href:
                            platform = "mega"
                            m_match = re.search(r'mega\.nz/(file|folder|#F!|#!)[\w!/-]*', href)
                            if m_match:
                                platform = "mega"
                                link_type = "archive"
                                file_id = "unknown" # Mega links are complex, just tag as platform
                        elif "pixeldrain.com" in href:
                            platform = "pixeldrain"
                            p_match = re.search(r'pixeldrain\.com/(?:u|l)/([a-zA-Z0-9-]+)', href)
                            if p_match:
                                file_id = p_match.group(1)
                                link_type = "file"
                        
                        if platform and file_id:
                            # Skip if already added in this thread
                            if any(l['url'] == href for l in all_links):
                                continue
                                
                            # Metadata detection from surrounding text
                            context_text = post.get_text()
                            
                            # Detection patterns
                            quality = None
                            q_match = re.search(r'(1080p|720p|4k|2160p|h\.264|h\.265)', context_text, re.I)
                            if q_match: quality = q_match.group(1)
                            
                            duration = None
                            d_match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?)', context_text)
                            if d_match: duration = d_match.group(1)
                            
                            # Determine Title (Cleanup link text if it's just a raw URL)
                            title = link_text
                            if not title or "http" in title or len(title) < 3:
                                # Try to find text right before the link
                                prev_text = link_elem.previous_sibling
                                if prev_text and isinstance(prev_text, str) and len(prev_text.strip()) > 3:
                                    title = prev_text.strip().split('\n')[-1].strip()
                                else:
                                    title = f"{platform.capitalize()} {link_type.capitalize()}"
                            
                            # Assign thumbnail
                            thumbnail = None
                            has_preview = False
                            if img_idx < len(post_images):
                                thumbnail = post_images[img_idx]
                                has_preview = True
                                img_idx += 1
                            elif platform == "bunkr" and link_type == "video":
                                thumbnail = f"https://thumb-p1.bunkr.ru/{file_id}-200x200.jpg"
                            
                            all_links.append({
                                "url": href,
                                "title": title,
                                "type": link_type,
                                "platform": platform,
                                "thumbnail": thumbnail,
                                "id": file_id,
                                "has_preview": has_preview,
                                "duration": duration,
                                "quality": quality
                            })
                
                # Find next page link
                next_page_elem = soup.select_one('a.pageNav-jump--next')
                if next_page_elem and 'href' in next_page_elem.attrs:
                    next_href = next_page_elem['href']
                    if not next_href.startswith('http'):
                        current_url = self.base_url + ('' if next_href.startswith('/') else '/') + next_href
                    else:
                        current_url = next_href
                    pages_visited += 1
                else:
                    current_url = None
            except Exception as e:
                logger.error(f"Error extracting links from thread {current_url}: {e}")
                break
        
        # Remove duplicates based on URL
        unique_links = []
        seen_urls = set()
        for link in all_links:
            if link["url"] not in seen_urls:
                unique_links.append(link)
                seen_urls.add(link["url"])
                
        return unique_links

if __name__ == "__main__":
    # Example usage
    # scout = XenForoExtractor("https://simpcity.su")
    # results = scout.search("onlyfans")
    # print(results)
    pass
