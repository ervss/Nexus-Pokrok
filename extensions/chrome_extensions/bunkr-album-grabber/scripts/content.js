(function () {
    console.log("Bunkr Album Grabber: Content script loaded.");

    function getAlbumData() {
        const items = Array.from(document.querySelectorAll('.grid-images_box, .box, .col-xs-6, .col-md-4, .video-item'));
        const bunkrLinkPattern = /\/(v|f)\/([a-zA-Z0-9]+)/;
        const turboLinkPattern = /turbo\.cr\/[a-zA-Z0-9\/]+/;

        const results = [];
        const seen = new Set();

        // 1. Turbo.cr Detection
        if (window.location.href.includes("turbo.cr")) {
            console.log("Bunkr Grabber: Detected turbo.cr page");

            // On turbo.cr album page, look for video items in grid or table
            const turboItems = document.querySelectorAll('.video-item, .grid-item, .file-item, tr, [class*="file"], [class*="video"]');
            console.log(`Bunkr Grabber: Found ${turboItems.length} potential items on turbo.cr`);

            if (turboItems.length > 0) {
                turboItems.forEach((item, index) => {
                    // Look for links within the item
                    const link = item.querySelector('a[href*="turbo.cr"]') ||
                                 item.querySelector('a[href*="/v/"]') ||
                                 item.querySelector('a[href*="/f/"]');

                    if (!link) return;

                    const href = link.href;
                    if (seen.has(href)) return;

                    // Extract metadata from table or grid
                    const nameEl = item.querySelector('.name, td:first-child, a');
                    const title = nameEl ? nameEl.innerText.trim() : link.innerText.trim() || "Turbo Video";

                    // Try to find thumbnail
                    const img = item.querySelector('img');
                    const thumbnail = img ? img.src : null;

                    // Look for file type (TYPE column in table)
                    const typeCell = item.querySelector('[class*="TYPE"], td:nth-child(2), .type');
                    const fileType = typeCell ? typeCell.innerText.trim().toLowerCase() : "";

                    // Look for file size info
                    const sizeText = item.querySelector('.size, td')?.innerText || "";

                    // Add all video files (mp4, avi, mkv, webm, mov, etc.)
                    const isVideoFile = href.includes('.mp4') ||
                                       href.includes('.avi') ||
                                       href.includes('.mkv') ||
                                       href.includes('.webm') ||
                                       href.includes('.mov') ||
                                       href.includes('/v/') ||
                                       title.toLowerCase().match(/\.(mp4|avi|mkv|webm|mov)/) ||
                                       fileType === 'mp4' ||
                                       fileType === 'video' ||
                                       item.querySelector('[type="mp4"]');

                    if (isVideoFile) {
                        console.log(`Bunkr Grabber: Adding turbo.cr video ${index + 1}: ${title}`);
                        results.push({
                            url: href,
                            thumbnail: thumbnail,
                            title: title,
                            type: "turbo"
                        });
                        seen.add(href);
                    }
                });
            }

            console.log(`Bunkr Grabber: Total turbo.cr videos found: ${results.length}`);
        }

        // 2. Tnaflix Detection
        if (window.location.href.includes("tnaflix.com")) {
            const label = document.querySelector('meta[property="og:title"]')?.content || "Tnaflix Video";
            const thumb = document.querySelector('meta[property="og:image"]')?.content;

            // If we are on a single video page
            if (window.location.href.includes("/video")) {
                results.push({
                    url: window.location.href,
                    thumbnail: thumb,
                    title: label,
                    type: "tnaflix"
                });
                seen.add(window.location.href);
            }
            // If on profile, maybe grab basic info or just let backend handle it?
            // Since backend handles profile crawling, we can just add the profile URL if user wants to import *this* page.
            else if (window.location.href.includes("/profile/")) {
                results.push({
                    url: window.location.href,
                    thumbnail: thumb,
                    title: "Profile: " + label,
                    type: "tnaflix_profile"
                });
                seen.add(window.location.href);
            }
        }

        // 3. Bunkr / Generic Box Logic / Tnaflix Listing
        // Tnaflix listings also use <a> tags with thumbnails
        items.forEach(item => {
            const link = item.querySelector('a[href]');
            if (!link) return;

            const href = link.href;
            if (seen.has(href)) return;

            // Check if it is a Bunkr link OR a Tnaflix video link OR turbo.cr
            const isBunkr = bunkrLinkPattern.test(href);
            const isTnaflix = href.includes("tnaflix.com") && href.includes("/video");
            const isTurbo = turboLinkPattern.test(href);

            if (isBunkr || isTnaflix || isTurbo) {
                // Try to find a title
                const title = item.querySelector('p, span, .name, .title')?.innerText?.trim() || "Video";

                // FILTER: Ignore trailers
                if (title.toLowerCase().includes('trailer') || href.toLowerCase().includes('trailer')) {
                    return;
                }

                // Try to find a thumbnail
                const img = item.querySelector('img');
                const thumbnail = img ? img.src : null;

                // Extract Duration (e.g. "12:34")
                const durationText = item.querySelector('.duration, .video-time, .time, .video-duration, .thumb-icon.video-duration')?.innerText?.trim() || "";

                // Extract Quality (e.g. "1080p")
                const qualityText = item.querySelector('.quality, .hd-badge, .badge-hd, .max-quality, .thumb-icon.max-quality')?.innerText?.trim() || "";
                let quality = 0;
                // Tnaflix uses "4p" to represent 4K/2160p
                if (qualityText === '4p' || qualityText.toLowerCase().includes('2160') || qualityText.toLowerCase().includes('4k')) quality = 2160;
                else if (qualityText.toLowerCase().includes('1080')) quality = 1080;
                else if (qualityText.toLowerCase().includes('720')) quality = 720;
                else if (qualityText.toLowerCase().includes('480')) quality = 480;

                results.push({
                    url: href,
                    thumbnail: thumbnail,
                    title: title,
                    durationText: durationText,
                    quality: quality
                });
                seen.add(href);
            }
        });

        // Fallback if no grid items found (maybe a list view or different layout)
        if (results.length === 0 || (results.length === 1 && results[0].type === "tnaflix_profile")) {
            const links = Array.from(document.querySelectorAll('a[href]'));
            links.forEach(a => {
                if (seen.has(a.href)) return;

                const isBunkr = bunkrLinkPattern.test(a.href);
                const isTnaflix = a.href.includes("tnaflix.com") && a.href.includes("/video");
                const isTurbo = turboLinkPattern.test(a.href);

                if (isBunkr || isTnaflix || isTurbo) {
                    seen.add(a.href);

                    // Try to find nearby duration/quality in parent
                    const parent = a.closest('.video-item, .box, .grid-item, div');
                    const durationText = parent?.querySelector('.duration, .video-time, .time, .video-duration, .thumb-icon.video-duration')?.innerText?.trim() || "";
                    const qText = parent?.querySelector('.quality, .hd-badge, .max-quality, .thumb-icon.max-quality')?.innerText?.trim() || "";
                    let q = 0;
                    // Tnaflix uses "4p" to represent 4K/2160p
                    if (qText === '4p' || qText.includes('2160') || qText.includes('4k')) q = 2160;
                    else if (qText.includes('1080')) q = 1080;
                    else if (qText.includes('720')) q = 720;

                    results.push({
                        url: a.href,
                        thumbnail: null,
                        title: a.innerText.trim() || "Video Link",
                        durationText: durationText,
                        quality: q
                    });
                }
            });
        }

        return results;
    }

    // Listen for messages from popup
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        if (request.action === "get_links") {
            const data = getAlbumData();
            sendResponse({ links: data });
        }
    });
})();
