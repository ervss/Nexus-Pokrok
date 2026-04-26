/* ============================================
   BUNKR NEXUS - Intelligent Media Discovery
   ============================================ */

class BunkrNexus {
    constructor() {
        this.overlay = null;
        this.results = [];
        this.isSearching = false;
        this.autoHeal = true;
        this.init();
    }

    init() {
        this.createOverlay();
        
        // Keybind: Alt + B for Bunkr Nexus
        document.addEventListener('keydown', (e) => {
            if (e.altKey && e.key.toLowerCase() === 'b') {
                e.preventDefault();
                this.open();
            }
            if (e.key === 'Escape' && this.isOpen()) {
                this.close();
            }
        });
    }

    createOverlay() {
        const html = `
            <div class="bunkr-nexus-overlay" id="bunkrNexusOverlay">
                <div class="bunkr-nexus-container">
                    <header class="bunkr-header">
                        <div class="bunkr-logo-row">
                            <div class="bunkr-logo">
                                <span class="material-icons-round">hub</span>
                                BUNKR<span>NEXUS</span>
                            </div>
                            <button class="quantum-search-close" onclick="bunkrNexus.close()">×</button>
                        </div>
                        <div class="bunkr-search-wrapper">
                            <span class="material-icons-round bunkr-search-icon">search</span>
                            <input type="text" id="bunkrSearchInput" class="bunkr-search-input" placeholder="Discovery across 10+ Bunkr mirrors..." autocomplete="off">
                            <div id="bunkrLoading" style="position:absolute; right:20px; top:50%; transform:translateY(-50%); display:none;">
                                <div class="spinner-small"></div>
                            </div>
                        </div>
                    </header>

                    <main class="bunkr-results-scroll" id="bunkrResultsContainer">
                        <div class="quantum-search-empty">
                            <div class="quantum-search-empty-icon" style="font-size: 80px; opacity:0.1;">folder_special</div>
                            <div class="quantum-search-empty-text">Enter query to begin Bunkr Deep-Scan</div>
                        </div>
                    </main>

                    <footer class="bunkr-stats">
                        <div id="bunkrResultStatus" style="color:#6b7280; font-size:13px;">Ready for operation</div>
                        <label class="bunkr-heal-toggle">
                            <input type="checkbox" checked onchange="bunkrNexus.autoHeal = this.checked" style="display:none;">
                            <div class="toggle-switch"></div>
                            <span>Auto-Heal & Metadata Sync</span>
                        </label>
                    </footer>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', html);
        this.overlay = document.getElementById('bunkrNexusOverlay');
        
        const input = document.getElementById('bunkrSearchInput');
        let searchTimeout;
        input.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            const query = e.target.value.trim();
            if (query.length >= 3) {
                searchTimeout = setTimeout(() => this.search(query), 600);
            }
        });
    }

    async search(query) {
        if (this.isSearching) return;
        this.isSearching = true;
        this.showLoading(true);

        const container = document.getElementById('bunkrResultsContainer');
        container.innerHTML = `<div class="bunkr-grid">${Array(12).fill('<div class="bunkr-card bunkr-skeleton" style="height:200px; background:#111118; border-radius:12px;"></div>').join('')}</div>`;

        try {
            const response = await fetch(`/api/v1/search/external?query=${encodeURIComponent(query)}&source=Bunkr`);
            const data = await response.json();
            
            // Filter only Bunkr results (in case backend sends more)
            this.results = (data.results || []).filter(r => r.source.toLowerCase().includes('bunkr'));
            this.renderResults();
            
            document.getElementById('bunkrResultStatus').innerHTML = `Found <strong>${this.results.length}</strong> Bunkr assets across the network`;
        } catch (error) {
            console.error('Bunkr search error:', error);
            container.innerHTML = `<div class="quantum-search-empty">Error searching. Please try again.</div>`;
        } finally {
            this.isSearching = false;
            this.showLoading(false);
        }
    }

    renderResults() {
        const container = document.getElementById('bunkrResultsContainer');
        if (this.results.length === 0) {
            container.innerHTML = `<div class="quantum-search-empty">No results found for this query.</div>`;
            return;
        }

        container.innerHTML = `
            <div class="bunkr-grid">
                ${this.results.map((r, i) => this.renderCard(r, i)).join('')}
            </div>
        `;
    }

    renderCard(result, index) {
        const isAlbum = result.url.includes('/a/') || result.url.includes('/album/');
        const type = isAlbum ? 'album' : 'video';
        const thumb = result.thumbnail || '/static/placeholder.jpg';
        
        // Serialize result to JSON for the onclick handler
        const resultJson = JSON.stringify(result).replace(/'/g, "\\'");

        return `
            <div class="bunkr-card" style="animation: slideUp 0.4s ease forwards; animation-delay: ${index * 0.03}s">
                <div class="bunkr-thumb-container">
                    <img src="${thumb}" alt="${result.title}" loading="lazy">
                    <div class="bunkr-type-badge ${type}">${type}</div>
                    
                    <div class="bunkr-actions">
                        <button class="bunkr-action-btn primary" onclick='bunkrNexus.import(${resultJson})'>
                            <span class="material-icons-round">move_to_inbox</span> Import Asset
                        </button>
                        <button class="bunkr-action-btn" onclick="window.open('${result.url}', '_blank')">
                            <span class="material-icons-round">open_in_new</span> Visit Source
                        </button>
                    </div>
                </div>
                <div class="bunkr-card-info">
                    <div class="bunkr-card-title" title="${result.title}">${result.title}</div>
                    <div class="bunkr-card-meta">
                        <span class="material-icons-round" style="font-size:12px;">public</span>
                        ${result.source.split(' ')[1] || 'Bunkr'}
                    </div>
                </div>
            </div>
        `;
    }

    async import(result) {
        const { url, title } = result;
        // Show success immediately for "wow" effect
        if (window.showToast) {
            window.showToast(`Importing ${title}... Healing enabled.`, 'info', 'sync');
        }

        try {
            const response = await fetch('/api/v1/import/text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    urls: [url],
                    items: [{
                        url: url,
                        title: title,
                        thumbnail: result.thumbnail,
                        source_url: url
                    }],
                    batch_name: `Bunkr Nexus Discovery`,
                    auto_heal: this.autoHeal
                })
            });
            
            if (response.ok) {
                if (window.showToast) window.showToast(`Success! ${title} added to Nexus.`, 'success', 'check_circle');
            } else {
                throw new Error('Import failed');
            }
        } catch (e) {
            console.error(e);
            if (window.showToast) window.showToast('Import failed. Check server logs.', 'error', 'error');
        }
    }

    showLoading(show) {
        const loader = document.getElementById('bunkrLoading');
        if (loader) loader.style.display = show ? 'block' : 'none';
    }

    open() {
        this.overlay.classList.add('active');
        document.getElementById('bunkrSearchInput').focus();
    }

    close() {
        this.overlay.classList.remove('active');
    }

    isOpen() {
        return this.overlay.classList.contains('active');
    }
}

// Global initialization
const bunkrNexus = new BunkrNexus();
