/* Nexus Bunkr Explorer - Content Script */

const NEXUS_API = 'http://localhost:8001/api/v1/import/bulk';

function init() {
    console.log('🚀 Nexus Bunkr Explorer active');
    const observer = new MutationObserver((mutations) => {
        injectButtons();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    injectButtons();
}

function injectButtons() {
    // Select the album items on bunkr-albums.io
    const albums = document.querySelectorAll('.rounded-xl.bg-mute.border-b:not(.nx-processed)');
    
    albums.forEach(album => {
        album.classList.add('nx-processed');
        const albumLink = album.querySelector("a[href^='https://bunkr.']");
        if (!albumLink) return;

        const container = album.querySelector('.flex-1.grid.auto-rows-max');
        if (!container) return;

        const btnContainer = document.createElement('div');
        btnContainer.className = 'nx-btn-container';

        // 1. Preview Button
        const previewBtn = document.createElement('button');
        previewBtn.className = 'nx-btn';
        previewBtn.innerHTML = '🔍 Smart Preview';
        previewBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            openPreview(albumLink.href, album.querySelector('p.text-subs span')?.innerText || 'Album');
        };

        // 2. Nexus Import Button
        const nexusBtn = document.createElement('button');
        nexusBtn.className = 'nx-btn nx-btn-primary';
        nexusBtn.innerHTML = '🚀 Send to Nexus';
        nexusBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            sendToNexus(albumLink.href, album.querySelector('p.text-subs span')?.innerText || 'Bunkr Album');
        };

        btnContainer.append(previewBtn, nexusBtn);
        container.appendChild(btnContainer);
    });
}

async function openPreview(albumUrl, title) {
    const overlay = document.createElement('div');
    overlay.className = 'nx-preview-overlay';
    let activePort = '8001';
    let selectedIndices = new Set();
    let allItemsData = [];

    overlay.innerHTML = `
        <div class="nx-preview-content">
            <div class="nx-preview-header">
                <div class="nx-preview-title-group">
                    <div class="nx-preview-title">${title}</div>
                    <div class="nx-target-group">
                        <button class="nx-target-btn" data-port="8000">8000</button>
                        <button class="nx-target-btn active" data-port="8001">8001</button>
                        <button class="nx-target-btn" data-port="8002">8002</button>
                        <div style="width: 1px; background: var(--nx-border); margin: 0 4px;"></div>
                        <button class="nx-btn nx-btn-primary nx-import-selected-btn">🚀 Import Selected (<span id="nx-sel-count">0</span>)</button>
                        <button class="nx-btn nx-btn-primary nx-import-all-btn" style="background: #4b5563;">🚀 All</button>
                    </div>
                </div>
                <div class="nx-filter-container">
                    <input type="text" class="nx-filter-input" placeholder="Filter files...">
                    <button class="nx-btn nx-btn-success nx-copy-all">📋 Copy Links</button>
                    <button class="nx-close-btn">&times;</button>
                </div>
            </div>
            <div class="nx-preview-grid">
                <div class="nx-loader"></div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    const selCountEl = overlay.querySelector('#nx-sel-count');
    overlay.querySelector('.nx-close-btn').onclick = () => overlay.remove();
    overlay.onclick = (e) => { if(e.target === overlay) overlay.remove(); };

    // Target buttons logic
    const targetBtns = overlay.querySelectorAll('.nx-target-btn');
    targetBtns.forEach(btn => {
        btn.onclick = (e) => {
            targetBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activePort = btn.getAttribute('data-port');
        };
    });

    overlay.querySelector('.nx-import-all-btn').onclick = () => {
        sendToNexus(albumUrl, title, activePort);
    };

    overlay.querySelector('.nx-import-selected-btn').onclick = () => {
        if (selectedIndices.size === 0) return alert('No videos selected!');
        const selectedVideos = Array.from(selectedIndices).map(idx => allItemsData[idx]);
        sendBatchToNexus(`Selected from ${title}`, selectedVideos, activePort);
    };

    try {
        const response = await fetch(albumUrl);
        const text = await response.text();
        const doc = new DOMParser().parseFromString(text, 'text/html');
        const grid = overlay.querySelector('.nx-preview-grid');
        grid.innerHTML = '';

        const items = Array.from(doc.querySelectorAll('.grid-images .theItem'));
        const albumDomain = new URL(albumUrl).hostname;
        const allFiles = [];

        items.forEach((item, index) => {
            const img = item.querySelector('.grid-images_box-img');
            const fileLink = item.querySelector("a[href^='/f/']");
            if (!img || !fileLink) return;

            const fileUrl = `https://${albumDomain}${fileLink.getAttribute('href')}`;
            const fileSize = findSize(item);
            const fileDate = findDate(item);
            const isVideo = !!item.querySelector('[class*="video"]') || !!item.querySelector('.grid-images_box-icon');
            const fileName = item.querySelector('p')?.innerText || 
                             item.querySelector('.grid-images_box-name')?.innerText || 'File';

            allItemsData.push({ 
                url: fileUrl, 
                title: fileName,
                source_url: albumUrl,
                filesize: parseSize(fileSize)
            });

            const el = document.createElement('div');
            el.className = 'nx-preview-item';
            el.setAttribute('data-title', fileName.toLowerCase());
            
            let metaString = '';
            if (fileSize) metaString += fileSize;
            if (fileDate) metaString += (metaString ? ' | ' : '') + fileDate;

            el.innerHTML = `
                <div class="nx-click-shield"></div>
                <div class="nx-select-indicator"></div>
                <div class="nx-item-main">
                    <img src="${img.src}" loading="lazy">
                    <div class="nx-item-title">${fileName}</div>
                    <div class="nx-item-actions">
                        <button class="nx-action-btn nx-play-btn">▶ Play</button>
                        <button class="nx-action-btn nx-import-btn">🚀 Import</button>
                    </div>
                </div>
                <div class="nx-video-overlay"></div>
                <div class="nx-item-meta">
                    <span class="nx-badge">${metaString || '...'}</span>
                    ${isVideo ? '<span class="nx-badge nx-video-icon">▶</span>' : ''}
                </div>
            `;
            
            const videoOverlay = el.querySelector('.nx-video-overlay');
            
            // Fix Selection - Catch all clicks via shield
            el.querySelector('.nx-click-shield').onclick = (e) => {
                e.stopPropagation();
                el.classList.toggle('selected');
                if (el.classList.contains('selected')) {
                    selectedIndices.add(index);
                } else {
                    selectedIndices.delete(index);
                }
                selCountEl.innerText = selectedIndices.size;
            };

            el.querySelector('.nx-play-btn').onclick = async (e) => {
                e.stopPropagation();
                const btn = e.target;
                const originalText = btn.innerText;
                btn.innerText = '⌛ Loading...';
                
                chrome.runtime.sendMessage({ type: 'RESOLVE_STREAM', url: fileUrl }, (response) => {
                    if (response?.success && response.streamUrl) {
                        btn.innerText = originalText;
                        videoOverlay.innerHTML = `
                            <video src="${response.streamUrl}" controls autoplay style="width:100%; height:100%;"></video>
                            <button class="nx-close-player" title="Close Player">&times;</button>
                        `;
                        videoOverlay.classList.add('active');
                        
                        videoOverlay.querySelector('.nx-close-player').onclick = (ev) => {
                            ev.stopPropagation();
                            videoOverlay.classList.remove('active');
                            videoOverlay.innerHTML = '';
                        };
                    } else {
                        btn.innerText = '❌ Error';
                        setTimeout(() => btn.innerText = originalText, 2000);
                        window.open(fileUrl, '_blank'); 
                    }
                });
            };

            el.querySelector('.nx-import-btn').onclick = (e) => {
                e.stopPropagation();
                sendSingleToNexus(fileUrl, fileName, albumUrl, fileSize, activePort);
            };

            el.onclick = () => window.open(fileUrl, '_blank');
            grid.appendChild(el);
        });

        // Search Filter
        const filterInput = overlay.querySelector('.nx-filter-input');
        filterInput.oninput = (e) => {
            const term = e.target.value.toLowerCase().trim();
            grid.querySelectorAll('.nx-preview-item').forEach(item => {
                item.style.display = item.getAttribute('data-title').includes(term) ? 'block' : 'none';
            });
        };

        // Copy All
        overlay.querySelector('.nx-copy-all').onclick = () => {
            const visibleUrls = Array.from(grid.querySelectorAll('.nx-preview-item'))
                .filter(el => el.style.display !== 'none')
                .map(el => {
                    const idx = Array.from(grid.children).indexOf(el);
                    return allFiles[idx].url;
                }).join('\n');
            
            navigator.clipboard.writeText(visibleUrls);
            const btn = overlay.querySelector('.nx-copy-all');
            btn.innerText = '✅ Copied!';
            setTimeout(() => btn.innerText = '📋 Copy Links', 2000);
        };
    } catch (err) {
        console.error('Preview failed', err);
        overlay.querySelector('.nx-preview-grid').innerHTML = '<p style="color:red; margin: auto;">Failed to load album data.</p>';
    }
}

function findSize(item) {
    const text = item.innerText || '';
    // Look for patterns like "1.57 GB" or "500 MB" or "1,2 GB"
    // We filter out anything less than 1KB to avoid fake metadata like "4 b"
    const match = text.match(/(\d+[,\.]?\d*)\s*(GB|MB|KB)/i);
    return match ? match[0].trim() : '';
}

function findDate(item) {
    const text = item.innerText || '';
    // Look for patterns like "15:42:15 03/04/2026" or "03/04/2026"
    const match = text.match(/(\d{2}:\d{2}(:\d{2})?\s+)?\d{2}\/\d{2}\/\d{4}/);
    return match ? match[0].trim() : '';
}

async function sendBatchToNexus(batchName, videos, port) {
    const payload = {
        batch_name: batchName,
        videos: videos
    };
    chrome.runtime.sendMessage({ type: 'IMPORT_TO_NEXUS', payload, port }, (response) => {
        if (response?.success) {
            alert(`🚀 Success! Imported ${videos.length} videos to port ${port}.`);
        } else {
            alert(`❌ Import failed: ${response?.error}`);
        }
    });
}

function injectOriginal(container, imgSrc, fileName, fileUrl, fileSize) {
    container.innerHTML = `
        <img src="${imgSrc}" loading="lazy">
        <div class="nx-item-title">${fileName}</div>
        <div class="nx-item-actions">
            <button class="nx-action-btn nx-play-btn">▶ Play</button>
            <button class="nx-action-btn nx-import-btn">🚀 Import</button>
        </div>
    `;
    // Re-bind (simplified for this example, in real app better to use a template)
    location.reload(); // Refreshing the view is safest for now to re-bind everything
}

async function sendSingleToNexus(url, title, sourceUrl, sizeStr, port = '8001') {
    const payload = {
        batch_name: `Bunkr Single: ${title}`,
        videos: [{
            title: title,
            url: url,
            source_url: sourceUrl,
            filesize: parseSize(sizeStr)
        }]
    };

    chrome.runtime.sendMessage({ type: 'IMPORT_TO_NEXUS', payload, port }, (response) => {
        if (response?.success) {
            alert(`🚀 Success! Imported to Nexus on port ${port}.`);
        } else {
            alert(`❌ Import failed on ${port}: ${response?.error || 'Unknown error'}`);
        }
    });
}

async function sendToNexus(albumUrl, title, port = '8001') {
    try {
        const response = await fetch(albumUrl);
        const text = await response.text();
        const doc = new DOMParser().parseFromString(text, 'text/html');
        const items = Array.from(doc.querySelectorAll('.grid-images .theItem'));
        const albumDomain = new URL(albumUrl).hostname;

        const videos = items.map(item => {
            const fileLink = item.querySelector("a[href^='/f/']");
            if (!fileLink) return null;
            return {
                title: item.querySelector('p')?.innerText || 'Bunkr Video',
                url: `https://${albumDomain}${fileLink.getAttribute('href')}`,
                source_url: albumUrl,
                filesize: parseSize(findSize(item))
            };
        }).filter(v => v !== null);

        const payload = {
            batch_name: `Bunkr: ${title}`,
            videos: videos
        };

        chrome.runtime.sendMessage({ type: 'IMPORT_TO_NEXUS', payload, port }, (response) => {
            if (response?.success) {
                alert(`🚀 Success! Sent ${videos.length} items to Nexus Dashboard on port ${port}.`);
            } else {
                alert(`❌ Import failed on ${port}: ${response?.error || 'Unknown error'}`);
            }
        });

    } catch (err) {
        alert(`❌ Import failed on ${port}: ${err.message}`);
    }
}

function parseSize(sizeStr) {
    if (!sizeStr) return 0;
    const match = sizeStr.match(/([\d\.]+)\s*(GB|MB|KB|B)/i);
    if (!match) return 0;
    const val = parseFloat(match[1]);
    const unit = match[2].toUpperCase();
    if (unit === 'GB') return val * 1024 * 1024 * 1024;
    if (unit === 'MB') return val * 1024 * 1024;
    if (unit === 'KB') return val * 1024;
    return val;
}

init();
