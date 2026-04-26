// Nexus Bunkr Explorer - Background Service Worker

chrome.runtime.onInstalled.addListener(() => {
  console.log('Nexus Bunkr Explorer installed.');
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'IMPORT_TO_NEXUS') {
        const { payload, port } = request;
        const url = `http://localhost:${port}/api/v1/import/bulk`;

        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => {
            if (res.ok) {
                sendResponse({ success: true, count: payload.videos.length });
            } else {
                sendResponse({ success: false, error: `Server error ${res.status}` });
            }
        })
        .catch(err => {
            sendResponse({ success: false, error: err.message });
        });

        return true; // Keep message channel open for async response
    } else if (request.type === 'RESOLVE_STREAM') {
        fetch(request.url)
            .then(res => res.text())
            .then(html => {
                const patterns = [
                    /https?:\/\/[^"']+\.(mp4|m4v|mov|mkv)[^"']*/i,
                    /src\s*:\s*["'](https?:\/\/[^"']+)["']/i,
                    /source\s+src=["'](https?:\/\/[^"']+)["']/i
                ];
                let foundUrl = null;
                for (const pattern of patterns) {
                    const match = html.match(pattern);
                    if (match && (match[0].includes('cdn') || match[0].includes('stream') || match[0].includes('media'))) {
                        foundUrl = match[0].replace(/&amp;/g, '&').replace(/["']/g, '');
                        break;
                    }
                }
                if (foundUrl) {
                    sendResponse({ success: true, streamUrl: foundUrl });
                } else {
                    sendResponse({ success: false });
                }
            })
            .catch(() => sendResponse({ success: false }));
        return true;
    }
});
