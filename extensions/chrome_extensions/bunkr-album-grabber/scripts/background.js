chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "fetch_video_url") {
        extractViaTab(request.url)
            .then(directUrl => sendResponse({ directUrl }))
            .catch(error => sendResponse({ error: error.message }));
        return true;
    }
});

async function extractViaTab(pageUrl) {
    return new Promise((resolve, reject) => {
        let tabId = null;
        const timeout = setTimeout(() => {
            if (tabId) chrome.tabs.remove(tabId);
            reject(new Error("Extraction timed out after 10 seconds."));
        }, 10000);

        chrome.tabs.create({ url: pageUrl, active: false }, (tab) => {
            tabId = tab.id;

            const listener = (updatedTabId, changeInfo) => {
                if (updatedTabId === tabId && changeInfo.status === 'complete') {
                    // Inject extraction script
                    chrome.scripting.executeScript({
                        target: { tabId: tabId },
                        func: () => {
                            const findMedia = () => {
                                // Special handling for turbo.cr
                                if (window.location.href.includes('turbo.cr')) {
                                    const results = [];

                                    // 1. Check video elements
                                    document.querySelectorAll('video').forEach(video => {
                                        if (video.src && video.src.endsWith('.mp4') && !video.src.startsWith('blob:')) {
                                            results.push(video.src);
                                        }
                                        if (video.currentSrc && video.currentSrc.endsWith('.mp4') && !video.currentSrc.startsWith('blob:')) {
                                            results.push(video.currentSrc);
                                        }
                                        video.querySelectorAll('source').forEach(s => {
                                            if (s.src && s.src.endsWith('.mp4')) results.push(s.src);
                                        });
                                    });

                                    // 2. Search entire page HTML (outerHTML includes everything)
                                    const pageHtml = document.documentElement.outerHTML || '';
                                    const mp4Regex = /https?:\/\/[^\s"'<>()]+\.mp4[^\s"'<>)]*/gi;
                                    const htmlMatches = pageHtml.match(mp4Regex) || [];
                                    htmlMatches.forEach(u => results.push(u));

                                    // 3. Search each script tag's content
                                    document.querySelectorAll('script').forEach(script => {
                                        const txt = script.textContent || script.innerHTML || '';
                                        if (!txt) return;
                                        const scriptMatches = txt.match(mp4Regex) || [];
                                        scriptMatches.forEach(u => results.push(u));
                                    });

                                    // Deduplicate and filter
                                    const unique = Array.from(new Set(results)).map(u => u.trim()).filter(Boolean);
                                    const filtered = unique.filter(url =>
                                        !url.startsWith('blob:') &&
                                        !url.includes('logo') &&
                                        !url.includes('favicon') &&
                                        !url.includes('thumb') &&
                                        !url.toLowerCase().includes('preview') &&
                                        url.length > 50
                                    );

                                    if (filtered.length > 0) return filtered[0];
                                    if (unique.length > 0) return unique[0];
                                }

                                // 1. Check video tags
                                const video = document.querySelector('video source') || document.querySelector('video');
                                if (video && video.src && !video.src.startsWith('blob:')) return video.src;

                                // 2. Check for explicit download links with common video extensions
                                const extensions = ['.mp4', '.mkv', '.m4v', '.mov', '.m3u8'];
                                const links = Array.from(document.querySelectorAll('a[href]'));
                                for (const link of links) {
                                    const href = link.href.toLowerCase();
                                    if (extensions.some(ext => href.endsWith(ext)) && !href.includes('bunkr.') && !href.includes('turbo.cr')) {
                                        // Usually direct links are on cdn domains, not bunkr.* or turbo.cr main domains
                                        return link.href;
                                    }
                                    if (link.innerText.toLowerCase().includes('download') && extensions.some(ext => href.includes(ext))) {
                                        return link.href;
                                    }
                                }

                                // 3. Regex search in HTML for CDN patterns (Video only)
                                const html = document.documentElement.innerHTML;
                                // Unified regex for video extensions on CDN domains
                                const mediaRegex = /https?:\/\/[a-zA-Z0-9-.]+\.[a-z]{2,}\/[^"']+\.(mp4|mkv|m4v|mov|m3u8)/gi;
                                const matches = html.match(mediaRegex);
                                if (matches) {
                                    // Filter out common false positives if any
                                    const filtered = matches.filter(m => !m.includes('favicon') && !m.includes('logo'));
                                    if (filtered.length > 0) return filtered[0];
                                }

                                // 4. Check for 'src' in any script tags that might be JSON config
                                const scripts = Array.from(document.querySelectorAll('script'));
                                for (const script of scripts) {
                                    const content = script.innerHTML;
                                    const match = content.match(/"(https?:\/\/[^"]+\.(mp4|m4v|mov|m3u8)[^"]*)"/i);
                                    if (match) return match[1].replace(/\\/g, '');
                                }

                                return null;
                            };
                            return findMedia();
                        }
                    }).then((results) => {
                        const directUrl = results[0]?.result;
                        if (directUrl) {
                            cleanup();
                            resolve(directUrl);
                        } else {
                            // Wait shorter for JS-heavy pages (faster retry)
                            setTimeout(() => {
                                chrome.scripting.executeScript({
                                    target: { tabId: tabId },
                                    func: () => {
                                        // Turbo.cr retry logic
                                        if (window.location.href.includes('turbo.cr')) {
                                            const results = [];

                                            // Check video elements
                                            document.querySelectorAll('video').forEach(video => {
                                                if (video.src && video.src.endsWith('.mp4') && !video.src.startsWith('blob:')) {
                                                    results.push(video.src);
                                                }
                                                if (video.currentSrc && video.currentSrc.endsWith('.mp4') && !video.currentSrc.startsWith('blob:')) {
                                                    results.push(video.currentSrc);
                                                }
                                                video.querySelectorAll('source').forEach(s => {
                                                    if (s.src && s.src.endsWith('.mp4')) results.push(s.src);
                                                });
                                            });

                                            // Search entire page HTML
                                            const pageHtml = document.documentElement.outerHTML || '';
                                            const mp4Regex = /https?:\/\/[^\s"'<>()]+\.mp4[^\s"'<>)]*/gi;
                                            const htmlMatches = pageHtml.match(mp4Regex) || [];
                                            htmlMatches.forEach(u => results.push(u));

                                            // Search script tags
                                            document.querySelectorAll('script').forEach(script => {
                                                const txt = script.textContent || script.innerHTML || '';
                                                if (!txt) return;
                                                const scriptMatches = txt.match(mp4Regex) || [];
                                                scriptMatches.forEach(u => results.push(u));
                                            });

                                            // Deduplicate and filter
                                            const unique = Array.from(new Set(results)).map(u => u.trim()).filter(Boolean);
                                            const filtered = unique.filter(url =>
                                                !url.startsWith('blob:') &&
                                                !url.includes('logo') &&
                                                !url.includes('favicon') &&
                                                !url.includes('thumb') &&
                                                !url.toLowerCase().includes('preview') &&
                                                url.length > 50
                                            );

                                            if (filtered.length > 0) return filtered[0];
                                            if (unique.length > 0) return unique[0];
                                        }

                                        const v = document.querySelector('video source') || document.querySelector('video');
                                        if (v && v.src && !v.src.startsWith('blob:')) return v.src;

                                        const html = document.documentElement.innerHTML;
                                        const mediaRegex = /https?:\/\/[a-zA-Z0-9-.]+\.[a-z]{2,}\/[^"']+\.(mp4|mkv|m4v|mov|m3u8)/gi;
                                        const matches = html.match(mediaRegex);
                                        return matches ? matches[0] : null;
                                    }
                                }).then((results2) => {
                                    const directUrl2 = results2[0]?.result;
                                    cleanup();
                                    if (directUrl2) resolve(directUrl2);
                                    else reject(new Error("Direct link matching patterns not found."));
                                });
                            }, 1500);
                        }
                    }).catch(err => {
                        cleanup();
                        reject(err);
                    });
                }
            };

            const cleanup = () => {
                clearTimeout(timeout);
                chrome.tabs.onUpdated.removeListener(listener);
                chrome.tabs.remove(tabId);
            };

            chrome.tabs.onUpdated.addListener(listener);
        });
    });
}
