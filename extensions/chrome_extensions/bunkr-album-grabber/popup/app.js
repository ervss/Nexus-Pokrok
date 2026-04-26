document.addEventListener('DOMContentLoaded', () => {
    const statsEl = document.getElementById('stats');
    const extractBtn = document.getElementById('extractBtn');
    const resultsList = document.getElementById('resultsList');
    const progressSection = document.getElementById('progressSection');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const copyBtn = document.getElementById('copyBtn');
    const exportBtn = document.getElementById('exportBtn');
    const limitSection = document.getElementById('limitSection');
    const linkLimitInput = document.getElementById('linkLimit');
    const downloadBtn = document.getElementById('downloadBtn');
    const copyPageUrlsBtn = document.getElementById('copyPageUrlsBtn');
    const quickExtractSection = document.getElementById('quickExtractSection');
    const quickExtractLimitInput = document.getElementById('quickExtractLimit');

    let collectedPageLinks = []; // Array of {url, title, thumbnail}
    let extractedDirectLinks = [];

    // 1. Initial scan
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const activeTab = tabs[0];
        if (!activeTab || !activeTab.url) return;

        chrome.scripting.executeScript({
            target: { tabId: activeTab.id },
            files: ['scripts/content.js']
        }).then(() => {
            chrome.tabs.sendMessage(activeTab.id, { action: "get_links" }, (response) => {
                if (chrome.runtime.lastError) {
                    console.error(chrome.runtime.lastError);
                    statsEl.innerText = "Chyba: Skúste obnoviť stránku.";
                    return;
                }
                if (response && response.links) {
                    collectedPageLinks = response.links;
                    statsEl.innerText = `Nájdených ${collectedPageLinks.length} položiek.`;
                    if (collectedPageLinks.length > 0) {
                        extractBtn.disabled = false;
                        limitSection.style.display = 'block';
                        linkLimitInput.value = collectedPageLinks.length;

                        // Enable "Copy Page URLs" button with limit input
                        quickExtractSection.style.display = 'block';
                        quickExtractLimitInput.value = collectedPageLinks.length;
                        copyPageUrlsBtn.disabled = false;
                        copyPageUrlsBtn.innerText = `📋 KOPÍROVAŤ URLS (${collectedPageLinks.length})`;
                    }
                } else {
                    statsEl.innerText = "Žiadne videá nenájdené.";
                }
            });
        }).catch(err => {
            console.error(err);
            statsEl.innerText = "Chyba injekcie skriptu.";
        });
    });

    // 2. Extract process
    extractBtn.addEventListener('click', async () => {
        // Check if this is turbo.cr - if so, skip extraction
        const isTurboAlbum = collectedPageLinks.some(item => item.type === 'turbo');
        if (isTurboAlbum) {
            statsEl.innerText = "⚠️ Turbo.cr linky nie je možné extrahovať. Použite tlačidlo KOPÍROVAŤ URLS vyššie.";
            return;
        }

        extractBtn.disabled = true;
        limitSection.style.display = 'none';
        progressSection.style.display = 'block';
        resultsList.innerHTML = '';
        extractedDirectLinks = [];

        const limit = parseInt(linkLimitInput.value) || collectedPageLinks.length;
        const minQuality = parseInt(document.getElementById('minQuality').value) || 0;
        const minDurationMinutes = parseInt(document.getElementById('minDuration').value) || 0;

        // Helper to convert "MM:SS" or "HH:MM:SS" to minutes
        const getMinutes = (str) => {
            if (!str) return 0;
            const parts = str.split(':').map(p => parseInt(p) || 0);
            if (parts.length === 2) return parts[0] + (parts[1] / 60);
            if (parts.length === 3) return (parts[0] * 60) + parts[1] + (parts[2] / 60);
            return 0;
        };

        const linksToProcess = collectedPageLinks.filter(item => {
            const qOk = (item.quality || 0) >= minQuality;
            const dOk = getMinutes(item.durationText) >= minDurationMinutes;
            return qOk && dOk;
        }).slice(0, limit);

        if (linksToProcess.length === 0) {
            statsEl.innerText = "Žiadne položky nevyhovujú filtrom.";
            extractBtn.disabled = false;
            limitSection.style.display = 'block';
            progressSection.style.display = 'none';
            return;
        }

        let processed = 0;
        const total = linksToProcess.length;
        const CONCURRENCY_LIMIT = 2; // Keep it low for stability

        const processLink = async (item, itemEl) => {
            const statusEl = itemEl.querySelector('.item-status');
            const urlEl = itemEl.querySelector('.item-url');

            statusEl.innerText = "Spracovávam...";
            statusEl.className = "item-status status-loading";

            try {
                // Try up to 2 times
                let directUrl = null;
                for (let attempt = 1; attempt <= 2; attempt++) {
                    const result = await new Promise((resolve) => {
                        chrome.runtime.sendMessage({ action: "fetch_video_url", url: item.url }, resolve);
                    });
                    if (result && result.directUrl) {
                        directUrl = result.directUrl;
                        break;
                    }
                    if (attempt === 1) statusEl.innerText = "Retrying (2/2)...";
                }

                if (directUrl) {
                    // FILTER: Discard trailers found after extraction
                    if (directUrl.toLowerCase().includes('trailer.mp4')) {
                        statusEl.innerText = "Trailer (Preskočené) ⏭️";
                        statusEl.className = "item-status status-error";
                        return false;
                    }

                    extractedDirectLinks.push(directUrl);
                    statusEl.innerText = "Získané ✅";
                    statusEl.className = "item-status status-success";
                    urlEl.innerText = directUrl;

                    // Add a quick action button
                    const actions = document.createElement('div');
                    actions.className = 'item-actions';
                    actions.innerHTML = `<button class="btn-mini" data-url="${directUrl}">Pustiť</button>`;
                    itemEl.appendChild(actions);

                    actions.querySelector('button').addEventListener('click', () => {
                        window.open(directUrl, '_blank');
                    });

                    return true;
                } else {
                    statusEl.innerText = "Zlyhanie ❌";
                    statusEl.className = "item-status status-error";
                    return false;
                }
            } catch (err) {
                statusEl.innerText = "Chyba / Timeout";
                statusEl.className = "item-status status-error";
                return false;
            } finally {
                processed++;
                const percent = (processed / total) * 100;
                progressFill.style.width = `${percent}%`;
                progressText.innerText = `${processed} / ${total}`;
                resultsList.scrollTop = resultsList.scrollHeight;
            }
        };

        // Create UI items
        const linkMap = linksToProcess.map(item => {
            const itemEl = document.createElement('div');
            itemEl.className = 'result-item';

            const thumbHtml = item.thumbnail ? `<img src="${item.thumbnail}" class="item-thumb">` : `<div class="item-thumb-placeholder">?</div>`;
            const durationBadge = item.durationText ? `<span class="badge-mini">${item.durationText}</span>` : '';
            const qualityBadge = item.quality ? `<span class="badge-mini badge-quality">${item.quality}p</span>` : '';

            itemEl.innerHTML = `
                ${thumbHtml}
                <div class="item-info">
                    <div class="item-title">${item.title}</div>
                    <div class="item-meta">${durationBadge} ${qualityBadge} <span class="item-status">Čakám...</span></div>
                    <div class="item-url">${item.url}</div>
                </div>
            `;
            resultsList.appendChild(itemEl);
            return { item, itemEl };
        });

        // Batch execution
        for (let i = 0; i < linkMap.length; i += CONCURRENCY_LIMIT) {
            const batch = linkMap.slice(i, i + CONCURRENCY_LIMIT);
            await Promise.all(batch.map(entry => processLink(entry.item, entry.itemEl)));
        }

        statsEl.innerText = `Hotovo! Extrahovaných: ${extractedDirectLinks.length} / ${total}.`;
        if (extractedDirectLinks.length > 0) {
            copyBtn.disabled = false;
            exportBtn.disabled = false;
            downloadBtn.disabled = false;
        }
    });

    // 3. Actions
    copyBtn.addEventListener('click', () => {
        if (extractedDirectLinks.length === 0) return;
        navigator.clipboard.writeText(extractedDirectLinks.join('\n')).then(() => {
            const old = copyBtn.innerText;
            copyBtn.innerText = "✅ SKOPÍROVANÉ!";
            setTimeout(() => copyBtn.innerText = old, 2000);
        });
    });

    exportBtn.addEventListener('click', () => {
        if (extractedDirectLinks.length === 0) return;
        const blob = new Blob([extractedDirectLinks.join('\n')], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'bunkr_direct_links.txt';
        a.click();
        URL.revokeObjectURL(url);
    });

    downloadBtn.addEventListener('click', () => {
        if (extractedDirectLinks.length === 0) return;
        if (!confirm(`Chystáte sa stiahnuť ${extractedDirectLinks.length} súborov. Pokračovať?`)) return;

        extractedDirectLinks.forEach((url, index) => {
            // Delay downloads slightly to prevent browser freezing
            setTimeout(() => {
                chrome.downloads.download({
                    url: url,
                    conflictAction: 'uniquify'
                });
            }, index * 200);
        });
    });

    // 4. Copy Page URLs (turbo.cr requires backend processing)
    copyPageUrlsBtn.addEventListener('click', async () => {
        if (collectedPageLinks.length === 0) return;

        // Get the limit from the input
        const limit = parseInt(quickExtractLimitInput.value) || collectedPageLinks.length;
        const linksToExtract = collectedPageLinks.slice(0, limit);

        // For turbo.cr: Just copy page URLs (backend will handle extraction)
        // turbo.cr uses blob: URLs that cannot be extracted client-side
        const urlList = linksToExtract.map(item => item.url).join('\n');

        navigator.clipboard.writeText(urlList).then(() => {
            const old = copyPageUrlsBtn.innerText;
            copyPageUrlsBtn.innerText = "✅ SKOPÍROVANÉ!";
            setTimeout(() => copyPageUrlsBtn.innerText = old, 2000);
        });
    });
});
