// Quantum Explorer — Background Service Worker
// Handles context menu "Import to Nexus" from any page

const PORTS = [8000, 8001, 8002, 8003, 8004, 8005];
const PH_DEBUG_KEY = 'ph_debug_last';

chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: 'qe-import-link',
        title: '⬆ Import to Nexus',
        contexts: ['link'],
    });
    chrome.contextMenus.create({
        id: 'qe-import-page',
        title: '⬆ Import current page to Nexus',
        contexts: ['page'],
    });
    chrome.contextMenus.create({
        id: 'qe-import-video',
        title: '⬆ Import video to Nexus',
        contexts: ['video'],
    });
});

async function findDashboardUrl() {
    const stored = await chrome.storage.local.get(['selected_port']);
    const preferredPort = stored.selected_port || 8000;
    const check = async (port) => {
        try {
            const resp = await fetch(`http://localhost:${port}/api/v1/config/gofile_token`, {
                signal: AbortSignal.timeout(600),
            }).catch(() => null);
            return resp && resp.ok;
        } catch { return false; }
    };
    if (await check(preferredPort)) return `http://localhost:${preferredPort}`;
    for (const port of PORTS) {
        if (port === preferredPort) continue;
        if (await check(port)) return `http://localhost:${port}`;
    }
    return `http://localhost:${preferredPort}`;
}

async function importUrl(url, title, thumbnail) {
    if (!url) return;
    const dashUrl = await findDashboardUrl();
    try {
        const resp = await fetch(`${dashUrl}/api/v1/import/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                batch_name: `Context Menu: ${new Date().toLocaleDateString()}`,
                videos: [{
                    title: title || url,
                    url,
                    source_url: url,
                    thumbnail: thumbnail || null,
                    filesize: 0,
                    quality: 'HD',
                    duration: 0,
                }],
            }),
        });
        const ok = resp.ok;
        chrome.notifications?.create({
            type: 'basic',
            iconUrl: 'icon.png',
            title: 'Quantum Explorer',
            message: ok ? `✅ Importované: ${title || url}` : `❌ Import zlyhal (${resp.status})`,
        });
    } catch (e) {
        console.error('Context menu import failed:', e);
        chrome.notifications?.create({
            type: 'basic',
            iconUrl: 'icon.png',
            title: 'Quantum Explorer',
            message: `❌ Import zlyhal: ${e.message}`,
        });
    }
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
    let url = null;
    let title = tab?.title || '';

    if (info.menuItemId === 'qe-import-link') {
        url = info.linkUrl;
    } else if (info.menuItemId === 'qe-import-page') {
        url = info.pageUrl || tab?.url;
    } else if (info.menuItemId === 'qe-import-video') {
        url = info.srcUrl || info.pageUrl || tab?.url;
    }

    if (url) await importUrl(url, title, null);
});

// ── PornHoarder stream interceptor ────────────────────────────────────────────
// Watches network requests from pornhoarder.io tabs for mp4/m3u8 URLs
const phPendingStreams = {}; // tabId -> { pageUrl, streamUrl }
const abPendingStreams = {}; // tabId -> { pageUrl, streamUrl }
const rbPendingStreams = {}; // tabId -> { pageUrl, streamUrl }

chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        const url = details.url;
        if (!(/\.(mp4|m3u8|mpd)(\?|$)/i.test(url) || /manifest|playlist|master/i.test(url))) return;

        chrome.tabs.get(details.tabId, (tab) => {
            if (chrome.runtime.lastError || !tab) return;
            const pageUrl = tab.url || '';
            if (/pornhoarder\.(io|net|pictures)\/watch\//i.test(pageUrl)) {
                if (/pornhoarder\.(io|net|pictures)/i.test(url)) return; // skip their own assets
                console.log('[PH webRequest] Captured stream:', url.substring(0, 100));
                phPendingStreams[details.tabId] = { pageUrl, streamUrl: url };
                reportCapturedStream(pageUrl, url, 'pornhoarder');
                return;
            }
            if (pageUrl.includes('archivebate.com/watch/')) {
                if (/archivebate\.com/i.test(url) && !/cdn\.archivebate\.com/i.test(url)) return;
                console.log('[AB webRequest] Captured stream:', url.substring(0, 100));
                abPendingStreams[details.tabId] = { pageUrl, streamUrl: url };
                reportCapturedStream(pageUrl, url, 'archivebate');
                return;
            }
            if (/rec-ur-bate\.com|recurbate\.com/i.test(pageUrl)) {
                if (/rec-ur-bate\.com|recurbate\.com/i.test(url) && !/\.(mp4|m3u8|mpd)(\?|$)/i.test(url)) return;
                console.log('[RB webRequest] Captured stream:', url.substring(0, 100));
                rbPendingStreams[details.tabId] = { pageUrl, streamUrl: url };
                reportCapturedStream(pageUrl, url, 'recurbate');
            }
        });
    },
    { urls: ['<all_urls>'] },
    []
);

async function reportCapturedStream(pageUrl, streamUrl, source = 'unknown') {
    const dashUrl = await findDashboardUrl();
    try {
        const res = await fetch(`${dashUrl}/api/v1/videos/update_stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_url: pageUrl, stream_url: streamUrl, source }),
        });
        const data = await res.json();
        console.log('[StreamCapture] Nexus updated:', data);
        await chrome.storage.local.set({
            [PH_DEBUG_KEY]: {
                ts: Date.now(),
                source,
                status: data.video_id ? 'updated' : (data.status || 'unknown'),
                pageUrl: pageUrl || '',
                streamUrl: streamUrl || '',
                videoId: data.video_id || null
            }
        });
        if (data.video_id) {
            chrome.notifications?.create({
                type: 'basic',
                iconUrl: 'icon.png',
                title: 'Quantum Explorer',
                message: `✅ Stream zachytený a uložený`,
            });
        }
    } catch(e) {
        console.warn('[StreamCapture] Nexus update failed:', e.message);
        await chrome.storage.local.set({
            [PH_DEBUG_KEY]: {
                ts: Date.now(),
                source,
                status: 'error',
                pageUrl: pageUrl || '',
                streamUrl: streamUrl || '',
                error: e.message || 'unknown_error'
            }
        });
    }
}

// Handle stream URL captured from player_t.php iframe
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.action === 'PH_GET_DEBUG') {
        chrome.storage.local.get([PH_DEBUG_KEY]).then((d) => {
            sendResponse({ ok: true, data: d[PH_DEBUG_KEY] || null });
        }).catch((e) => {
            sendResponse({ ok: false, error: e?.message || 'storage_error' });
        });
        return true;
    }
    if (msg.action !== 'PH_PLAYER_STREAM') return;
    const { pageUrl, streamUrl, isHls } = msg;
    if (!streamUrl) return;
    console.log('[PH Player BG] Stream received:', streamUrl.substring(0, 100));
    // Determine the page URL: could be referrer from player iframe or the tab URL
    chrome.tabs.get(sender.tab?.id || -1, (tab) => {
        const watchUrl = tab?.url || pageUrl || '';
        // For HLS, wrap in Nexus proxy so segments are served with correct headers
        let finalUrl = streamUrl;
        if (isHls || streamUrl.includes('.m3u8')) {
            findDashboardUrl().then(base => {
                const proxyUrl = `${base}/api/v1/proxy/hls?url=${encodeURIComponent(streamUrl)}`;
                reportCapturedStream(watchUrl, proxyUrl, 'pornhoarder');
            });
        } else {
            reportCapturedStream(watchUrl, finalUrl, 'pornhoarder');
        }
    });
});
