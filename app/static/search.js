// ============================================
// QUANTUM SEARCH - Advanced Search Interface
// ============================================

class QuantumSearch {
    constructor() {
        this.overlay = null;
        this.results = [];
        this.filteredResults = [];
        this.activeSource = 'all';
        this.isSearching = false;
        this.downloads = {};
        this.settings = JSON.parse(localStorage.getItem('quantum_settings') || '{"autoImport": false, "quality": "best"}');
        this.init();
    }

    init() {
        // Create overlay HTML
        this.createOverlay();
        this.startDownloadPolling();

        // Register keyboard shortcut (Ctrl+K or Cmd+K)
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                this.open();
            }

            // ESC to close
            if (e.key === 'Escape') {
                if (this.isSettingsOpen) {
                    this.toggleSettings();
                } else if (this.isOpen()) {
                    this.close();
                }
            }
        });
    }

    createOverlay() {
        const html = `
            <div class="quantum-search-overlay" id="quantumSearchOverlay">
                <div class="quantum-search-container">
                    <div class="quantum-search-header">
                        <h2 class="quantum-search-title">Quantum Search</h2>
                        <div class="header-actions" style="display:flex; gap:12px;">
                            <button class="quantum-search-btn-icon" onclick="quantumSearch.toggleSettings()" title="Settings">⚙️</button>
                            <button class="quantum-search-close" onclick="quantumSearch.close()">×</button>
                        </div>
                    </div>
                    
                    <div id="quantumSearchMainView">
                        <div class="quantum-search-input-container">
                            <span class="quantum-search-icon">🔍</span>
                            <input 
                                type="text" 
                                class="quantum-search-input" 
                                id="quantumSearchInput"
                                placeholder="Search across Erome, Coomer, Kemono, SimpCity, and more..."
                                autocomplete="off"
                            >
                            <div class="quantum-search-loading" id="quantumSearchLoading"></div>
                        </div>
                        
                        <div class="quantum-search-sources" id="quantumSearchSources">
                            <span class="source-badge active" data-source="all">All Sources</span>
                        </div>
                        
                        <div class="quantum-search-results" id="quantumSearchResults">
                            <div class="quantum-search-empty">
                                <div class="quantum-search-empty-icon">🎯</div>
                                <div class="quantum-search-empty-text">
                                    Enter a search query to discover content<br>
                                    <small style="opacity: 0.6;">Try searching for creators, models, or content</small>
                                </div>
                            </div>
                        </div>

                        <div class="quantum-search-stats" id="quantumSearchStats" style="display: none;">
                            <div class="quantum-search-count">
                                <strong id="quantumResultCount">0</strong> results found
                            </div>
                            <div class="quantum-search-actions">
                                <button class="quantum-btn" onclick="quantumSearch.exportResults()">
                                    Export URLs
                                </button>
                                <button class="quantum-btn primary" onclick="quantumSearch.importAll()">
                                    Import All
                                </button>
                            </div>
                        </div>
                    </div>

                    <div id="quantumSearchSettingsView" style="display: none; padding: 20px;">
                        <h3 style="color:white; margin-bottom: 20px;">Settings</h3>
                        <div class="setting-item" style="color:white; margin-bottom:15px;">
                            <label style="display:flex; align-items:center; gap:10px; cursor:pointer;">
                                <input type="checkbox" id="settingAutoImport" onchange="quantumSearch.saveSettings()"> 
                                Auto-Import downloaded files
                            </label>
                        </div>
                        <div class="setting-item" style="color:white;">
                            <label>Preferred Quality: 
                                <select id="settingQuality" onchange="quantumSearch.saveSettings()" style="background:#333; color:white; border:1px solid #555; padding:4px; border-radius:4px;">
                                    <option value="best">Best Available</option>
                                    <option value="1080p">1080p</option>
                                    <option value="720p">720p</option>
                                </select>
                            </label>
                        </div>
                        <button class="quantum-btn" onclick="quantumSearch.toggleSettings()" style="margin-top:20px;">Back to Search</button>
                    </div>
                    
                    <div class="quantum-search-footer" id="quantumSearchFooter" style="margin-top:auto; padding-top:10px; border-top:1px solid rgba(255,255,255,0.1); display:none;">
                       <div id="downloadStatus" style="color: rgba(255,255,255,0.7); font-size:12px; display:flex; align-items:center; gap:10px;">
                           <!-- Status injected here -->
                       </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
        this.overlay = document.getElementById('quantumSearchOverlay');

        // Bind events
        this.bindEvents();

        // Init settings UI state
        document.getElementById('settingAutoImport').checked = this.settings.autoImport;
        document.getElementById('settingQuality').value = this.settings.quality;
    }

    bindEvents() {
        const input = document.getElementById('quantumSearchInput');
        let searchTimeout;

        input.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value.trim();

            if (query.length >= 2) {
                searchTimeout = setTimeout(() => {
                    this.search(query);
                }, 500); // Debounce 500ms
            } else if (query.length === 0) {
                this.renderHistory();
            } else {
                this.clearResults();
            }
        });

        // Focus event
        input.addEventListener('focus', () => {
            if (input.value.trim().length === 0) {
                this.renderHistory();
            }
        });

        // Close on overlay click
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) {
                this.close();
            }
        });
    }

    async search(query) {
        if (this.isSearching) return;

        this.isSearching = true;
        this.showLoading(true);

        // Clear history immediately so loading state is visible
        const container = document.getElementById('quantumSearchResults');
        container.innerHTML = `
            <div class="quantum-search-empty" style="grid-column:1/-1;">
                <div class="quantum-search-empty-icon" style="font-size:32px;">🔍</div>
                <div class="quantum-search-empty-text">Searching across all sources…</div>
            </div>`;

        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 45000);
            const response = await fetch(`/api/v1/search/external?query=${encodeURIComponent(query)}`, { signal: controller.signal });
            clearTimeout(timer);
            const data = await response.json();

            this.results = data.results || [];
            this.filteredResults = this.results;
            this.updateSourceBadges();
            this.renderResults();
        } catch (error) {
            if (error.name === 'AbortError') {
                this.showError('Search timed out. Try a more specific query.');
            } else {
                console.error('Search error:', error);
                this.showError('Failed to search. Please try again.');
            }
        } finally {
            this.isSearching = false;
            this.showLoading(false);
        }
    }

    updateSourceBadges() {
        const sources = ['all'];
        const sourceCounts = {};

        this.results.forEach(result => {
            const source = result.source;
            if (!sources.includes(source)) {
                sources.push(source);
            }
            sourceCounts[source] = (sourceCounts[source] || 0) + 1;
        });

        const container = document.getElementById('quantumSearchSources');
        container.innerHTML = sources.map(source => {
            const count = source === 'all' ? this.results.length : (sourceCounts[source] || 0);
            const isActive = this.activeSource === source ? 'active' : '';
            return `
                <span class="source-badge ${isActive}" data-source="${source}" onclick="quantumSearch.filterBySource('${source}')">
                    ${source} ${count > 0 ? `(${count})` : ''}
                </span>
            `;
        }).join('');
    }

    filterBySource(source) {
        this.activeSource = source;

        if (source === 'all') {
            this.filteredResults = this.results;
        } else {
            this.filteredResults = this.results.filter(r => r.source === source);
        }

        this.renderResults();

        // Update active badge
        document.querySelectorAll('.source-badge').forEach(badge => {
            badge.classList.toggle('active', badge.dataset.source === source);
        });
    }

    renderResults() {
        if (this.filteredResults.length === 0) {
            const container = document.getElementById('quantumSearchResults');
            document.getElementById('quantumSearchStats').style.display = 'none';
            container.innerHTML = `
                <div class="quantum-search-empty" style="grid-column:1/-1;">
                    <div class="quantum-search-empty-icon">😶</div>
                    <div class="quantum-search-empty-text">No results found. Try a different query.</div>
                </div>`;
            return;
        }
        this.renderResultsList();
    }

    renderResultsList() {
        const container = document.getElementById('quantumSearchResults');
        const stats = document.getElementById('quantumSearchStats');
        const countEl = document.getElementById('quantumResultCount');

        if (!container) return;

        // Show stats
        stats.style.display = 'flex';
        countEl.textContent = this.filteredResults.length;

        // Clear container and show results
        container.innerHTML = '';

        // Render cards with capped staggered animation
        container.innerHTML = this.filteredResults.map((result, index) => {
            const displayIndex = Math.min(index, 20); // Cap animation delay
            const thumbnail = result.thumbnail || '🎬';
            const thumbnailHTML = result.thumbnail
                ? `<img src="${result.thumbnail}" alt="${result.title}" onerror="this.parentElement.innerHTML='🎬'">`
                : thumbnail;

            // Extract duration and quality
            let duration = result.duration || '';
            let quality = result.quality || '';

            // Format duration if it's a number (seconds) or already formatted
            const formatDuration = (d) => {
                if (!d) return '';
                const dStr = String(d).toLowerCase();
                if (dStr.includes(':') || dStr.includes('min') || dStr.includes('sec')) return d;

                const secs = parseInt(d);
                if (isNaN(secs) || secs <= 0) return d;

                const hh = Math.floor(secs / 3600);
                const mm = Math.floor((secs % 3600) / 60);
                const ss = secs % 60;

                if (hh > 0) return `${hh}:${mm.toString().padStart(2, '0')}:${ss.toString().padStart(2, '0')}`;
                return `${mm}:${ss.toString().padStart(2, '0')}`;
            };

            const formattedDuration = formatDuration(duration);
            const qualityBadge = quality ? `<div class="quality-badge">${quality}</div>` : '';
            const durationBadge = formattedDuration ? `<div class="duration-badge">${formattedDuration}</div>` : '';
            const countBadge = (result.video_count > 1) ? `<div class="count-badge">📦 ${result.video_count}</div>` : '';

            return `
                <div class="search-result-card" style="animation-delay: ${displayIndex * 0.05}s">
                    <div class="search-result-thumbnail" onclick="quantumSearch.openResult('${result.url}')">
                        ${thumbnailHTML}
                        ${qualityBadge}
                        ${durationBadge}
                        ${countBadge}
                        <div class="play-overlay">
                            <div class="play-icon">▶</div>
                        </div>
                    </div>
                    <div class="search-result-content">
                        <div class="search-result-title" onclick="quantumSearch.openResult('${result.url}')">${this.escapeHtml(result.title)}</div>
                        <div class="search-result-description" style="font-size: 11px; color: rgba(255,255,255,0.4); margin-bottom: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${this.escapeHtml(result.description || '')}</div>
                        <div class="search-result-meta">
                            <span class="search-result-source">${result.source}</span>
                        </div>
                        <div class="search-result-actions" style="display:flex; gap:6px;">
                            <button class="action-btn btn-stream" onclick="event.stopPropagation(); quantumSearch.streamResult('${result.url}', '${this.escapeHtml(result.title)}')" title="Play Now">
                                <span class="material-icons-round" style="font-size: 14px;">play_arrow</span> Play
                            </button>
                            <button class="action-btn btn-download" onclick="event.stopPropagation(); quantumSearch.downloadVideo('${result.url}', '${result.title.replace(/'/g, "\\'")}', this)" title="Download">
                                <span class="material-icons-round" style="font-size: 14px;">download</span> DL
                            </button>
                            <button class="action-btn btn-import" onclick="event.stopPropagation(); quantumSearch.importVideo('${result.url}', this)" title="Import to Library">
                                <span class="material-icons-round" style="font-size: 14px;">move_to_inbox</span> Import
                            </button>
                            <button class="action-btn" onclick="event.stopPropagation(); window.open('${result.url}', '_blank')" title="Open Source" style="flex:0; padding: 4px 8px;">
                                <span class="material-icons-round" style="font-size: 14px;">launch</span>
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // --- Action Methods ---

    downloadVideo(url, title, btnElement) {
        // Trigger backend aria2c download
        const btn = btnElement || event.target.closest('button');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="quantum-search-loading active" style="position:static; width:14px; height:14px; border-width:2px; margin-right:6px;"></span> Q...';

        fetch('/api/v1/download/external', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                title: title
            })
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'download_queued' || data.status === 'already_local') {
                    btn.innerHTML = '<span class="material-icons-round" style="font-size: 14px;">check_circle</span> Queued';
                    btn.style.color = '#4ade80';
                    btn.style.borderColor = '#4ade80';
                } else {
                    btn.innerHTML = '<span class="material-icons-round" style="font-size: 14px;">error</span> Error';
                    btn.style.color = '#ef4444';
                }
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.style.color = '';
                    btn.style.borderColor = '';
                }, 3000);
            })
            .catch(err => {
                console.error(err);
                btn.innerHTML = 'Error';
                setTimeout(() => {
                    btn.innerHTML = originalText;
                }, 2000);
            });
    }

    importVideo(url, btnElement) {
        // Find the result object to get metadata
        const result = this.filteredResults.find(r => r.url === url);
        
        // Reuse the batch import endpoint for a single file
        fetch('/api/v1/import/text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                urls: [url],
                items: result ? [result] : null,
                batch_name: `Single Import`
            })
        })
            .then(response => {
                if (response.ok) {
                    // Show toast or alert
                    const btn = btnElement || (event && event.target.closest('button'));
                    if (btn) {
                        const originalText = btn.innerHTML;
                        btn.innerHTML = '<span class="material-icons-round" style="font-size: 14px;">check</span> Queued';
                        btn.style.color = '#4ade80';
                        setTimeout(() => {
                            btn.innerHTML = originalText;
                            btn.style.color = '';
                        }, 2000);
                    }
                } else {
                    alert('Import failed');
                }
            })
            .catch(err => console.error(err));
    }

    isFavorite(url) {
        const favs = JSON.parse(localStorage.getItem('quantum_favorites') || '[]');
        return favs.some(f => f.url === url);
    }

    toggleFavorite(url, title, thumbnail) {
        const favs = JSON.parse(localStorage.getItem('quantum_favorites') || '[]');
        const index = favs.findIndex(f => f.url === url);

        if (index >= 0) {
            favs.splice(index, 1); // Remove
        } else {
            favs.push({ url, title, thumbnail, date: new Date().toISOString() });
        }

        localStorage.setItem('quantum_favorites', JSON.stringify(favs));
        this.renderResults(); // Re-render to update UI
    }

    openResult(url) {
        window.open(url, '_blank');
    }

    streamResult(url, title) {
        // Simple direct streaming (XVideos, Bunkr, etc. might have direct link)
        // For better experience, we can open a dedicated minimalist player
        // but for now, target blank is a good start OR we can try to trigger 
        // the main dashboard's player if we have the alpine scope.
        window.open(url, '_blank');
    }

    exportResults() {
        const urls = this.filteredResults.map(r => r.url).join('\n');
        const blob = new Blob([urls], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `quantum-search-results-${Date.now()}.txt`;
        a.click();
    }

    async importAll() {
        if (this.filteredResults.length === 0) return;

        const urls = this.filteredResults.map(r => r.url);

        try {
            const response = await fetch('/api/v1/import/text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    urls: urls,
                    items: this.filteredResults,
                    batch_name: `Quantum Search - ${new Date().toLocaleString()}`
                })
            });

            if (response.ok) {
                alert(`Successfully queued ${urls.length} URLs for import!`);
                this.close();
            } else {
                throw new Error('Import failed');
            }
        } catch (error) {
            console.error('Import error:', error);
            alert('Failed to import results. Please try again.');
        }
    }

    toggleSettings() {
        this.isSettingsOpen = !this.isSettingsOpen;
        const mainView = document.getElementById('quantumSearchMainView');
        const settingsView = document.getElementById('quantumSearchSettingsView');

        if (this.isSettingsOpen) {
            mainView.style.display = 'none';
            settingsView.style.display = 'block';
        } else {
            mainView.style.display = 'block';
            settingsView.style.display = 'none';
        }
    }

    saveSettings() {
        this.settings.autoImport = document.getElementById('settingAutoImport').checked;
        this.settings.quality = document.getElementById('settingQuality').value;
        localStorage.setItem('quantum_settings', JSON.stringify(this.settings));
    }

    startDownloadPolling() {
        let failCount = 0;
        const poll = () => {
            // Skip if closed and nothing active
            if (!this.isOpen() && Object.keys(this.downloads).length === 0) {
                setTimeout(poll, 3000);
                return;
            }
            fetch('/api/v1/downloads/active')
                .then(r => r.json())
                .then(data => {
                    failCount = 0;
                    this.downloads = data;
                    this.renderStatus();
                    setTimeout(poll, 1000);
                })
                .catch(() => {
                    failCount++;
                    // Exponential backoff: 2s, 4s, 8s … capped at 30s
                    const delay = Math.min(1000 * Math.pow(2, failCount), 30000);
                    setTimeout(poll, delay);
                });
        };
        setTimeout(poll, 1000);
    }

    renderStatus() {
        const footer = document.getElementById('quantumSearchFooter');
        const statusEl = document.getElementById('downloadStatus');

        const activeIds = Object.keys(this.downloads);

        if (activeIds.length === 0) {
            footer.style.display = 'none';
            return;
        }

        footer.style.display = 'block';

        // Visualization: show overall count plus per-download progress with speed
        const count = activeIds.length;

        let html = `
            <span class="material-icons-round" style="font-size:16px; color:#4ade80;">download</span>
            <span>Downloading ${count} item${count > 1 ? 's' : ''}...</span>
        `;

        activeIds.forEach(id => {
            const raw = this.downloads[id];
            const data = typeof raw === 'number' ? { percent: raw } : (raw || {});
            const p = typeof data.percent === 'number' ? data.percent : 0;
            const downloaded = typeof data.downloaded_mb === 'number' ? data.downloaded_mb : null;
            const total = typeof data.total_mb === 'number' ? data.total_mb : null;
            const speed = typeof data.speed_mb_s === 'number' ? data.speed_mb_s : null;

            const infoParts = [];
            if (downloaded != null && total != null) {
                infoParts.push(`${downloaded.toFixed(1)}/${total.toFixed(1)} MB`);
            }
            if (speed != null) {
                infoParts.push(`${speed.toFixed(1)} MB/s`);
            }

            html += `
                <div style="display:flex; align-items:center; gap:6px; margin-left: 10px; min-width: 140px;">
                    <div style="flex:1; height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden;">
                        <div style="width: ${p}%; height: 100%; background: #4ade80; transition: width 0.3s ease;"></div>
                    </div>
                    <span style="font-size:10px; min-width:30px;">${p}%</span>
                    ${infoParts.length ? `<span style="font-size:10px; color:#9ca3af; margin-left: 2px;">${infoParts.join(' · ')}</span>` : ''}
                </div>
            `;
        });

        statusEl.innerHTML = html;
    }

    open() {
        this.overlay.classList.add('active');
        setTimeout(() => {
            document.getElementById('quantumSearchInput').focus();
        }, 100);
    }

    close() {
        this.overlay.classList.remove('active');
        // Don't clear results, keep them for re-opening
    }

    isOpen() {
        return this.overlay.classList.contains('active');
    }

    showLoading(show) {
        const loader = document.getElementById('quantumSearchLoading');
        if (show) {
            loader.classList.add('active');
        } else {
            loader.classList.remove('active');
        }
    }

    showError(message) {
        const container = document.getElementById('quantumSearchResults');
        container.innerHTML = `
            <div class="quantum-search-empty">
                <div class="quantum-search-empty-icon">⚠️</div>
                <div class="quantum-search-empty-text">${message}</div>
            </div>
        `;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    async renderHistory() {
        const container = document.getElementById('quantumSearchResults');
        const stats = document.getElementById('quantumSearchStats');
        stats.style.display = 'none';

        try {
            const response = await fetch('/api/v1/search/history?limit=10');
            const history = await response.json();

            if (history.length === 0) {
                this.clearResults();
                return;
            }

            container.innerHTML = `
                <div class="search-history-container" style="grid-column: 1/-1;">
                    <h3 style="color: rgba(255,255,255,0.4); font-size: 14px; margin-bottom: 12px; margin-left: 5px;">Recent Searches</h3>
                    ${history.map(item => `
                        <div class="history-item" onclick="quantumSearch.applyHistory('${item.query.replace(/'/g, "\\'")}')">
                            <span class="material-icons-round">history</span>
                            <div class="history-query">${item.query}</div>
                            <div class="history-meta">${item.results_count} results • ${this.formatRelativeTime(item.created_at)}</div>
                        </div>
                    `).join('')}
                    <button class="quantum-btn" onclick="quantumSearch.clearResults()" style="margin-top: 15px; align-self: flex-start;">Clear View</button>
                </div>
            `;
        } catch (error) {
            console.error('History error:', error);
            this.clearResults();
        }
    }

    applyHistory(query) {
        const input = document.getElementById('quantumSearchInput');
        input.value = query;
        this.search(query);
    }

    formatRelativeTime(dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);

        if (diff < 60) return 'just now';
        if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return date.toLocaleDateString();
    }

    clearResults() {
        const container = document.getElementById('quantumSearchResults');
        const stats = document.getElementById('quantumSearchStats');
        const sourceContainer = document.getElementById('quantumSearchSources');

        container.innerHTML = `
            <div class="quantum-search-empty">
                <div class="quantum-search-empty-icon">🎯</div>
                <div class="quantum-search-empty-text">
                    Enter a search query to discover content<br>
                    <small style="opacity: 0.6;">Try searching for creators, models, or content</small>
                </div>
            </div>
        `;
        stats.style.display = 'none';

        // Reset sources
        this.results = [];
        this.filteredResults = [];
        sourceContainer.innerHTML = '<span class="source-badge active" data-source="all">All Sources</span>';
    }
}

// Initialize on page load
let quantumSearch;
document.addEventListener('DOMContentLoaded', () => {
    quantumSearch = new QuantumSearch();
    console.log('🔮 Quantum Search initialized! Press Ctrl+K to open.');
});
