// ==UserScript==
// @name Bunkr Albums Enhanced with Sorting
// @namespace https://github.com/WendysBro/bunkr-albums-autoload-previews
// @version 1.3.1
// @description Adds infinite scroll, hover previews, sorting, and filtering to Bunkr Albums pages
// @author WendysBro
// @match https://bunkr-albums.io/
// @match https://bunkr-albums.io/?*
// @match https://bunkr-albums.io/topalbums*
// @license MIT
// @homepageURL https://github.com/WendysBro/bunkr-albums-autoload-previews
// @supportURL https://github.com/WendysBro/bunkr-albums-autoload-previews/issues
// @grant none
// @icon https://www.google.com/s2/favicons?sz=64&domain=bunkrrr.org
// ==/UserScript==

(function () {
	'use strict';

	const CONFIG = {
		previewDelay: 250,
		maxPreviews: 60,
		previewSize: '160px',
		scrollThreshold: 600,
	};

	function addSortingControls() {
		const controls = document.createElement('div');
		controls.style = 'margin: 10px 0; display: flex; gap: 10px; align-items: center;';

		const label = document.createElement('label');
		label.textContent = 'Sort albums by:';
		label.style = 'color: white;';

		const select = document.createElement('select');
		select.innerHTML = `
<option value="default">Default</option>
<option value="name">Name (A–Z)</option>
<option value="count">File Count</option>
`;
		select.style = 'padding: 4px; border-radius: 6px;';

		select.addEventListener('change', () => sortAlbums(select.value));
		controls.append(label, select);

		const gridContainer = document.querySelector('div.grid.auto-rows-max.gap-1\\.5');
		if (gridContainer && gridContainer.parentElement) {
			gridContainer.parentElement.insertBefore(controls, gridContainer);
		}
	}

	function sortAlbums(method) {
		const container = document.querySelector('div.grid.auto-rows-max.gap-1\\.5');
		if (!container) return;

		const albums = Array.from(container.children);
		if (method === 'name') {
			albums.sort((a, b) => {
				const nameA = a.querySelector('p.text-subs span')?.textContent.trim().toLowerCase() || '';
				const nameB = b.querySelector('p.text-subs span')?.textContent.trim().toLowerCase() || '';
				return nameA.localeCompare(nameB);
			});
		} else if (method === 'count') {
			albums.sort((a, b) => {
				const countA = parseInt(a.querySelector('p.text-xs span')?.textContent.match(/\d+/)?.[0] || '0');
				const countB = parseInt(b.querySelector('p.text-xs span')?.textContent.match(/\d+/)?.[0] || '0');
				return countB - countA;
			});
		} else {
			return;
		}

		albums.forEach((album) => container.appendChild(album));
	}

	class BunkrAlbumsEnhanced {
		constructor() {
			this.nextPage = 2;
			this.loading = false;
			this.previewTimeout = null;
			this.isTopAlbumsPage = window.location.pathname.includes('/topalbums');
			this.init();
		}

		init() {
			this.setupInfiniteScroll();
			this.setupAllHoverPreviews();
			addSortingControls();
		}

		qs(selector, el = document) {
			return el.querySelector(selector);
		}

		qsa(selector, el = document) {
			return Array.from(el.querySelectorAll(selector));
		}

		getCurrentParams() {
			const params = new URLSearchParams(window.location.search);
			return this.isTopAlbumsPage ? { lapse: params.get('lapse') || '24h', page: this.nextPage } : { search: params.get('search') || '', page: this.nextPage };
		}

		getAlbumDomain(albumUrl) {
			const match = albumUrl.match(/https:\/\/(bunkr\.[a-z]+)/);
			return match ? match[1] : 'bunkr.cr';
		}

		setupInfiniteScroll() {
			if (!this.isLastPage()) {
				window.addEventListener('scroll', this.handleScroll.bind(this));
			}
		}

		isLastPage() {
			return !!this.qs('.text-center.text-xs.text-subtle');
		}

		handleScroll() {
			if (this.loading) return;
			const scrollPosition = window.innerHeight + window.scrollY;
			if (scrollPosition >= document.body.offsetHeight - CONFIG.scrollThreshold) {
				this.loadNextPage();
			}
		}

		async loadNextPage() {
			this.loading = true;
			const params = this.getCurrentParams();
			const url = this.isTopAlbumsPage 
				? `/topalbums?lapse=${params.lapse}&page=${params.page}` 
				: window.location.search.includes('search=') 
					? `/?search=${encodeURIComponent(params.search)}&page=${params.page}`
					: `/?page=${params.page}`;

			try {
				const response = await fetch(url);
				if (!response.ok) throw new Error(`Failed to load page ${params.page}`);

				const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
				const newAlbums = this.qsa('.rounded-xl.bg-mute.border-b', doc);
				const container = this.qs('div.grid.auto-rows-max.gap-1\\.5');

				if (newAlbums.length && container) {
					newAlbums.forEach((album) => this.setupHoverPreview(album));
					container.append(...newAlbums);
					this.nextPage++;

					// reapply sort if user selected a sort option
					const sortMethod = document.querySelector('select')?.value;
					if (sortMethod && sortMethod !== 'default') sortAlbums(sortMethod);
				} else {
					window.removeEventListener('scroll', this.handleScroll);
				}
			} catch (error) {
				console.error('[Bunkr Albums Enhanced]', error);
			} finally {
				this.loading = false;
			}
		}

		setupAllHoverPreviews() {
			this.qsa('.rounded-xl.bg-mute.border-b').forEach((album) => {
				this.setupHoverPreview(album);
			});
		}

		setupHoverPreview(album) {
			const albumLink = this.qs("a[href^='https://bunkr.']", album);
			if (!albumLink) return;
			const albumUrl = albumLink.href;

			const albumTextContainer = this.qs('.flex-1.grid.auto-rows-max', album);
			if (!albumTextContainer) return;

			const previewContainer = this.createPreviewContainer();
			albumTextContainer.appendChild(previewContainer);

			album.addEventListener('mouseenter', () => this.showPreview(albumUrl, previewContainer));
			album.addEventListener('mouseleave', () => this.hidePreview(previewContainer));
			album.addEventListener('click', (e) => this.handleAlbumClick(e, albumUrl, previewContainer));
		}

		createPreviewContainer() {
			const container = document.createElement('div');
			container.className = 'album-preview-flex';
			container.style = `
display: none;
flex-wrap: wrap;
justify-content: center;
gap: 8px;
padding: 10px;
background: #222;
border-radius: 5px;
margin-top: 10px;
max-width: 100%;
overflow: hidden;
`;
			return container;
		}

		async showPreview(albumUrl, container) {
			this.previewTimeout = setTimeout(async () => {
				if (container.innerHTML.trim()) {
					container.style.display = 'flex';
					return;
				}

				try {
					const response = await fetch(albumUrl);
					if (!response.ok) throw new Error('Failed to load album contents');

					const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
					const albumDomain = this.getAlbumDomain(albumUrl);
					
					// --- Album Metadata ---
					const headerText = this.qs('h1 + p', doc)?.textContent?.trim() || "";
					const metaMatch = headerText.match(/\(([^)]+)\)/);
					const albumMeta = metaMatch ? metaMatch[1] : "";
					
					const items = this.qsa('.grid-images .theItem', doc);

					container.innerHTML = '';
					
					// Info Bar
					const infoBar = document.createElement('div');
					infoBar.style = 'width: 100%; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #444; padding-bottom: 5px;';
					
					const searchInput = document.createElement('input');
					searchInput.placeholder = '🔍 Filter files...';
					searchInput.style = 'background: #222; color: #fff; border: 1px solid #555; border-radius: 4px; padding: 2px 8px; font-size: 11px; margin: 0 10px; flex: 1; outline: none;';
					searchInput.addEventListener('input', (e) => {
						const term = e.target.value.toLowerCase().trim();
						container.querySelectorAll('.preview-item-wrapper').forEach(el => {
							const title = el.getAttribute('data-title') || "";
							el.style.display = title.includes(term) ? 'block' : 'none';
						});
					});
					// Isolation to prevent album navigation
					['click', 'mousedown', 'mouseup', 'keydown', 'keyup'].forEach(evName => {
						searchInput.addEventListener(evName, (e) => e.stopPropagation());
					});
					
					const copyBtn = document.createElement('button');
					copyBtn.textContent = '📋 Links';
					copyBtn.style = 'background: #333; color: #fff; border: 1px solid #555; border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; white-space: nowrap;';
					copyBtn.addEventListener('click', (e) => {
						e.preventDefault();
						e.stopPropagation();
						const visibleItems = Array.from(container.querySelectorAll('.preview-item-wrapper'))
							.filter(el => el.style.display !== 'none');
						const links = visibleItems.map(el => el.getAttribute('data-url')).join('\n');
						navigator.clipboard.writeText(links).then(() => {
							const oldText = copyBtn.textContent;
							copyBtn.textContent = '✅ Copied!';
							setTimeout(() => copyBtn.textContent = oldText, 2000);
						});
					});
					copyBtn.addEventListener('click', (e) => e.stopPropagation());
					const infoText = document.createElement('span');
					infoText.style = 'color: #aaa; font-size: 11px; font-weight: bold; white-space: nowrap;';
					infoText.textContent = albumMeta || `${items.length} Files`;
					
					infoBar.append(infoText, searchInput, copyBtn);
					container.appendChild(infoBar);

					items.slice(0, CONFIG.maxPreviews).forEach((item) => {
						const img = this.qs('.grid-images_box-img', item);
						const fileLink = this.qs("a[href^='/f/']", item);
						
						// Robust size extraction via regex
						let size = "";
						const spans = Array.from(item.querySelectorAll('span'));
						const sizeMatch = spans.find(s => /^\s*[\d\.]+\s*(GB|MB|KB|B)\s*$/i.test(s.textContent));
						if (sizeMatch) {
							size = sizeMatch.textContent.trim();
						} else {
							// fallback to original selector if regex fails
							size = this.qs('.grid-images_box-size', item)?.textContent?.trim() || "";
						}
						
						const title = item.querySelector('p')?.textContent?.trim() || 
						              item.querySelector('.grid-images_box-name')?.textContent?.trim() || "";
						
						const isVideo = !!this.qs('[class*="video"]', item) || 
						              !!this.qs('.grid-images_box-icon', item) ||
						              !!this.qs('i.fa-video', item);
						
						if (img && fileLink) this.addPreviewItem(img, fileLink, albumDomain, size, isVideo, title, container);
					});

					container.style.display = 'flex';
				} catch (error) {
					console.error('[Bunkr Albums Enhanced]', error);
					container.innerHTML = '<p style="color:white">Preview unavailable</p>';
					container.style.display = 'flex';
				}
			}, CONFIG.previewDelay);
		}

		addPreviewItem(img, fileLink, domain, size, isVideo, title, container) {
			const wrapper = document.createElement('div');
			const fullUrl = `https://${domain}${fileLink.getAttribute('href')}`;
			wrapper.className = 'preview-item-wrapper';
			wrapper.setAttribute('data-title', title.toLowerCase());
			wrapper.setAttribute('data-url', fullUrl);
			wrapper.style = `position: relative; width: ${CONFIG.previewSize}; transition: transform 0.1s;`;

			const thumb = document.createElement('img');
			thumb.src = img.src;
			thumb.title = title;
			thumb.style = `width: 100%; height: auto; border-radius: 5px; cursor: pointer; border: 1px solid #444;`;
			thumb.alt = 'Preview';
			
			if (size) {
				const sizeBadge = document.createElement('span');
				sizeBadge.textContent = size;
				sizeBadge.style = 'position: absolute; bottom: 4px; right: 4px; background: rgba(0,0,0,0.8); color: #fff; font-size: 10px; padding: 1px 4px; border-radius: 3px; pointer-events: none; border: 0.5px solid #555;';
				wrapper.appendChild(sizeBadge);
			}

			if (isVideo) {
				const vidBadge = document.createElement('span');
				vidBadge.textContent = '▶';
				vidBadge.style = 'position: absolute; top: 4px; left: 4px; background: rgba(124, 58, 237, 0.9); color: #fff; font-size: 10px; width: 16px; height: 16px; display: flex; align-items: center; justify-content: center; border-radius: 50%; pointer-events: none; border: 0.5px solid #fff;';
				wrapper.appendChild(vidBadge);
			}

			wrapper.addEventListener('mouseenter', () => wrapper.style.transform = 'scale(1.05)');
			wrapper.addEventListener('mouseleave', () => wrapper.style.transform = 'scale(1)');

			wrapper.addEventListener('click', (e) => {
				e.preventDefault();
				e.stopPropagation();
				window.open(`https://${domain}${fileLink.getAttribute('href')}`, '_blank');
			});
			
			wrapper.appendChild(thumb);
			container.appendChild(wrapper);
		}

		hidePreview(container) {
			clearTimeout(this.previewTimeout);
			container.style.display = 'none';
		}

		handleAlbumClick(e, albumUrl, previewContainer) {
			// Ignore if clicking anywhere inside the preview area (filter, buttons, images)
			if (e.target.closest('.album-preview-flex')) {
				return;
			}
			window.location.href = albumUrl;
		}
	}

	new BunkrAlbumsEnhanced();
})();
