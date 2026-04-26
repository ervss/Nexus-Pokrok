// Nexus Universal Video Importer - Content Script

(function() {
    const SCAN_INTERVAL = 2000;
    const MIN_DURATION = 10; // Seconds

    function createOverlay(video) {
        if (video.dataset.nexusImporterActive) return;
        video.dataset.nexusImporterActive = 'true';

        const container = document.createElement('div');
        container.className = 'nexus-import-overlay';
        
        container.innerHTML = `
            <div class="nexus-import-btn">
                <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                Import to
            </div>
            <div class="nexus-port-menu">
                <div class="nexus-port-opt" data-port="8000">Nexus 8000 <span>MAIN</span></div>
                <div class="nexus-port-opt" data-port="8001">Nexus 8001 <span>DEV</span></div>
                <div class="nexus-port-opt" data-port="8002">Nexus 8002 <span>ALT</span></div>
            </div>
        `;

        // Position overlay relative to video parent or video itself
        const parent = video.parentElement;
        if (getComputedStyle(parent).position === 'static') {
            parent.style.position = 'relative';
        }
        parent.appendChild(container);

        container.querySelectorAll('.nexus-port-opt').forEach(opt => {
            opt.onclick = (e) => {
                e.stopPropagation();
                e.preventDefault();
                handleImport(video, opt.dataset.port);
            };
        });
    }

    async function handleImport(video, port) {
        showToast(`Preparing import for port ${port}...`);

        // Try to get URL from background script first (most reliable for HLS)
        chrome.runtime.sendMessage({ type: 'GET_CAPTURED_STREAM' }, (response) => {
            let streamUrl = response?.streamUrl;

            // Fallback to video src if background didn't capture anything yet
            if (!streamUrl) {
                streamUrl = video.currentSrc || video.src;
            }

            if (!streamUrl || streamUrl.startsWith('blob:')) {
                // If it's a blob and background didn't catch the m3u8, we might be stuck
                // unless we check for common player objects (Hls.js, etc)
                if (!streamUrl.startsWith('blob:')) {
                    showToast('Could not resolve direct video link.', true);
                    return;
                }
            }

            const metadata = {
                title: document.title.split(' - ')[0].trim(),
                sourceUrl: window.location.href,
                duration: Math.round(video.duration) || 0,
                thumbnail: findThumbnail()
            };

            chrome.runtime.sendMessage({
                type: 'IMPORT_VIDEO',
                streamUrl,
                port,
                metadata
            }, (res) => {
                if (res && res.success) {
                    showToast(`Successfully imported to port ${port}!`);
                } else {
                    showToast(`Failed: ${res?.error || 'Unknown error'}`, true);
                }
            });
        });
    }

    function findThumbnail() {
        // Try various ways to find a thumbnail
        const ogImage = document.querySelector('meta[property="og:image"]')?.content;
        if (ogImage) return ogImage;

        const poster = document.querySelector('video')?.poster;
        if (poster) return poster;

        return null;
    }

    function showToast(text, isError = false) {
        const toast = document.createElement('div');
        toast.className = 'nexus-toast';
        if (isError) toast.style.borderColor = 'rgba(255, 0, 0, 0.4)';
        toast.innerText = text;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    function scanVideos() {
        const videos = document.querySelectorAll('video');
        videos.forEach(video => {
            // Check duration (if available)
            if (video.duration && video.duration < MIN_DURATION) return;
            
            // Wait for metadata to be loaded if duration is NaN
            if (isNaN(video.duration)) {
                video.addEventListener('loadedmetadata', () => {
                    if (video.duration >= MIN_DURATION) {
                        createOverlay(video);
                    }
                }, { once: true });
            } else {
                createOverlay(video);
            }
        });
    }

    // Initial scan and periodic check for dynamic content
    scanVideos();
    setInterval(scanVideos, SCAN_INTERVAL);

})();
