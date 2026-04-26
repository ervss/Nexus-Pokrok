/* ============================================================
   NEXUS FUTURE · APP SHELL RUNTIME
   ------------------------------------------------------------
   Owns the cross-cutting UI:
     - Command palette (Ctrl/Cmd + Shift + P)
     - Keyboard shortcuts overlay (?)
     - Persistent mini-player (picks up current <video>)
     - Import drawer (URL auto-detect → queue)
     - Density toggle
     - Ambient color sampler for .player-container
     - Source chip tagging for .v-card
     - Swipe review (on /discovery/review pages)

   All mounted via DOM injection; zero dependency on Alpine,
   Jinja or existing dashboard code. Safe to include anywhere.
   ============================================================ */

(function () {
    'use strict';

    // ---------- Utility helpers ----------
    const $ = (sel, root = document) => root.querySelector(sel);
    const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
    const h = (tag, props = {}, children = []) => {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (k === 'class') el.className = v;
            else if (k === 'dataset') Object.assign(el.dataset, v);
            else if (k.startsWith('on') && typeof v === 'function') {
                el.addEventListener(k.slice(2).toLowerCase(), v);
            } else if (k === 'html') el.innerHTML = v;
            else if (k === 'text') el.textContent = v;
            else el.setAttribute(k, v);
        }
        for (const c of [].concat(children)) {
            if (c == null) continue;
            el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
        }
        return el;
    };

    const isTypingTarget = (el) =>
        el && (
            el.tagName === 'INPUT' ||
            el.tagName === 'TEXTAREA' ||
            el.isContentEditable ||
            el.closest?.('[contenteditable="true"]')
        );

    // Icon helper using inline SVG (tiny subset of Lucide).
    const icon = (name) => {
        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        const paths = ICONS[name] || ICONS.circle;
        svg.innerHTML = paths;
        return svg;
    };

    const ICONS = {
        search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        command: '<path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3 3 3 0 0 0-3-3H6a3 3 0 0 0-3 3 3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0 3 3h12a3 3 0 0 0 3-3 3 3 0 0 0-3-3Z"/>',
        play: '<polygon points="6 3 20 12 6 21 6 3"/>',
        pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
        close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
        arrowLeft: '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
        download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
        film: '<rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/>',
        compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
        settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>',
        chart: '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
        moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
        pip: '<rect width="18" height="14" x="3" y="5" rx="2"/><rect width="8" height="6" x="11" y="11" rx="1"/>',
        grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
        plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
        check: '<polyline points="20 6 9 17 4 12"/>',
        eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
        keyboard: '<rect x="2" y="4" width="20" height="16" rx="2" ry="2"/><path d="M6 8h.01"/><path d="M10 8h.01"/><path d="M14 8h.01"/><path d="M18 8h.01"/><path d="M8 12h.01"/><path d="M12 12h.01"/><path d="M16 12h.01"/><path d="M7 16h10"/>',
        sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
        circle: '<circle cx="12" cy="12" r="10"/>',
    };

    // ============================================================
    // 1) SOURCE CHIP TAGGING FOR EXISTING .v-card ELEMENTS
    // ============================================================
    const SOURCE_MAP = [
        { re: /bunkr/i, name: 'bunkr', token: '--nx-src-bunkr' },
        { re: /vk\.(com|ru)/i, name: 'vk', token: '--nx-src-vk' },
        { re: /eporner/i, name: 'eporner', token: '--nx-src-eporner' },
        { re: /xvideos/i, name: 'xvideos', token: '--nx-src-xvideos' },
        { re: /redgifs/i, name: 'redgifs', token: '--nx-src-redgifs' },
        { re: /reddit/i, name: 'reddit', token: '--nx-src-reddit' },
        { re: /camwhores/i, name: 'camwhores', token: '--nx-src-camwhores' },
        { re: /hqporner/i, name: 'hqporner', token: '--nx-src-hqporner' },
        { re: /whoreshub/i, name: 'whoreshub', token: '--nx-src-whoreshub' },
        { re: /webshare|wsfiles/i, name: 'webshare', token: '--nx-src-webshare' },
        { re: /erome/i, name: 'erome', token: '--nx-src-erome' },
        { re: /pixeldrain/i, name: 'pixeldrain', token: '--nx-src-pixeldrain' },
        { re: /gofile/i, name: 'gofile', token: '--nx-src-gofile' },
        { re: /telegram|t\.me/i, name: 'telegram', token: '--nx-src-telegram' },
        { re: /spankbang/i, name: 'spankbang', token: '--nx-src-spankbang' },
    ];

    function detectSource(str) {
        if (!str) return null;
        for (const src of SOURCE_MAP) if (src.re.test(str)) return src;
        return null;
    }

    function annotateCard(card) {
        if (card.dataset.nxAnnotated) return;
        card.dataset.nxAnnotated = '1';
        const text = [
            card.getAttribute('data-source') || '',
            card.getAttribute('data-url') || '',
            card.querySelector('a[href]')?.href || '',
            card.querySelector('img[src]')?.src || '',
        ].join(' ');
        const src = detectSource(text);
        if (!src) return;
        card.style.setProperty('--nx-src', `var(${src.token})`);
        const metaHost = card.querySelector('.v-meta') || card;
        if (!metaHost.querySelector('.nx-src-chip')) {
            const chip = h('span', { class: 'nx-src-chip', text: src.name });
            metaHost.prepend(chip);
        }
    }

    function annotateAllCards() {
        $$('.v-card').forEach(annotateCard);
    }

    // ============================================================
    // 2) COMMAND PALETTE
    // ============================================================
    const COMMANDS = [
        {
            group: 'Navigate',
            title: 'Library',
            desc: 'Go to main dashboard',
            shortcut: 'g l',
            icon: 'film',
            run: () => (window.location.href = '/'),
        },
        {
            group: 'Navigate',
            title: 'Discovery',
            desc: 'Auto-discovery profiles',
            shortcut: 'g d',
            icon: 'compass',
            run: () => (window.location.href = '/discovery'),
        },
        {
            group: 'Navigate',
            title: 'Statistics',
            desc: 'Charts and breakdowns',
            shortcut: 'g s',
            icon: 'chart',
            run: () => (window.location.href = '/stats'),
        },
        {
            group: 'Actions',
            title: 'Import from URL',
            desc: 'Open unified import drawer',
            shortcut: 'i',
            icon: 'download',
            run: () => NXShell.drawer.open(),
        },
        {
            group: 'Actions',
            title: 'Toggle Theater Mode',
            desc: 'Dim UI around the player',
            shortcut: 't',
            icon: 'moon',
            run: () => document.body.classList.toggle('nx-theater'),
        },
        {
            group: 'Actions',
            title: 'Toggle Mini-Player',
            desc: 'Pop current video into bottom-right',
            shortcut: 'p',
            icon: 'pip',
            run: () => NXShell.mini.toggle(),
        },
        {
            group: 'Density',
            title: 'Cinematic (2 cols)',
            desc: 'Large immersive cards',
            shortcut: '1',
            icon: 'grid',
            run: () => NXShell.density.set('cinematic'),
        },
        {
            group: 'Density',
            title: 'Cozy (3 cols)',
            desc: 'Balanced default',
            shortcut: '2',
            icon: 'grid',
            run: () => NXShell.density.set('cozy'),
        },
        {
            group: 'Density',
            title: 'Compact (info density)',
            desc: 'Fit as many as possible',
            shortcut: '3',
            icon: 'grid',
            run: () => NXShell.density.set('compact'),
        },
        {
            group: 'Help',
            title: 'Keyboard Shortcuts',
            desc: 'Show the cheatsheet',
            shortcut: '?',
            icon: 'keyboard',
            run: () => NXShell.keys.open(),
        },
    ];

    function fuzzyMatch(query, item) {
        if (!query) return true;
        const hay = (item.title + ' ' + item.desc + ' ' + item.group).toLowerCase();
        const q = query.toLowerCase();
        let i = 0;
        for (const ch of q) {
            i = hay.indexOf(ch, i);
            if (i === -1) return false;
            i++;
        }
        return true;
    }

    const palette = (() => {
        let root, input, list, selected = 0, filtered = COMMANDS;

        function mount() {
            root = h('div', { class: 'nx-palette-scrim', role: 'dialog', 'aria-label': 'Command Palette' }, [
                h('div', { class: 'nx-palette' }, [
                    h('div', { class: 'nx-palette-input-row' }, [
                        icon('search'),
                        input = h('input', {
                            class: 'nx-palette-input',
                            type: 'text',
                            placeholder: 'Type a command, or paste a URL…',
                            autocomplete: 'off',
                            spellcheck: 'false',
                        }),
                        h('span', { class: 'nx-palette-kbd', text: 'esc' }),
                    ]),
                    list = h('div', { class: 'nx-palette-list', role: 'listbox' }),
                ]),
            ]);
            root.addEventListener('click', (e) => {
                if (e.target === root) close();
            });
            input.addEventListener('input', render);
            input.addEventListener('keydown', onKey);
            document.body.appendChild(root);
            render();
        }

        function open() {
            if (!root) mount();
            root.dataset.open = 'true';
            input.value = '';
            selected = 0;
            render();
            requestAnimationFrame(() => input.focus());
        }

        function close() {
            root.dataset.open = 'false';
        }

        function toggle() {
            if (root?.dataset.open === 'true') close();
            else open();
        }

        function render() {
            const q = input.value.trim();
            // If it looks like a URL → prepend an import action.
            const quickActions = [];
            if (/^https?:\/\//i.test(q)) {
                quickActions.push({
                    group: 'Quick',
                    title: `Import URL`,
                    desc: q,
                    shortcut: '↵',
                    icon: 'download',
                    run: () => { close(); NXShell.drawer.open(q); },
                });
            }
            filtered = [...quickActions, ...COMMANDS.filter((c) => fuzzyMatch(q, c))];
            if (selected >= filtered.length) selected = Math.max(0, filtered.length - 1);

            list.innerHTML = '';
            if (!filtered.length) {
                list.appendChild(h('div', { class: 'nx-palette-empty', text: 'No matches. Try a URL or a verb.' }));
                return;
            }

            let currentGroup = null;
            filtered.forEach((cmd, idx) => {
                if (cmd.group !== currentGroup) {
                    currentGroup = cmd.group;
                    list.appendChild(h('div', { class: 'nx-palette-group-title', text: currentGroup }));
                }
                const row = h('div', {
                    class: 'nx-palette-item',
                    role: 'option',
                    'aria-selected': idx === selected ? 'true' : 'false',
                    dataset: { idx: String(idx) },
                    onmouseenter: () => { selected = idx; updateSelection(); },
                    onclick: () => { cmd.run(); close(); },
                }, [
                    h('span', { class: 'nx-palette-item-icon' }, [icon(cmd.icon)]),
                    h('div', { class: 'nx-palette-item-label' }, [
                        h('span', { class: 'nx-palette-item-title', text: cmd.title }),
                        h('span', { class: 'nx-palette-item-desc', text: cmd.desc }),
                    ]),
                    cmd.shortcut ? h('span', { class: 'nx-palette-item-shortcut', text: cmd.shortcut }) : null,
                ]);
                list.appendChild(row);
            });
        }

        function updateSelection() {
            $$('.nx-palette-item', list).forEach((el, idx) => {
                el.setAttribute('aria-selected', idx === selected ? 'true' : 'false');
                if (idx === selected) el.scrollIntoView({ block: 'nearest' });
            });
        }

        function onKey(e) {
            if (e.key === 'ArrowDown') { e.preventDefault(); selected = Math.min(filtered.length - 1, selected + 1); updateSelection(); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); selected = Math.max(0, selected - 1); updateSelection(); }
            else if (e.key === 'Enter') {
                e.preventDefault();
                const cmd = filtered[selected];
                if (cmd) { cmd.run(); close(); }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                close();
            }
        }

        return { open, close, toggle };
    })();

    // ============================================================
    // 3) KEYBOARD SHORTCUTS OVERLAY
    // ============================================================
    const KEYS_GROUPS = [
        {
            title: 'Global',
            rows: [
                ['Command palette', ['Ctrl', 'Shift', 'P']],
                ['Quantum search', ['Ctrl', 'K']],
                ['Import drawer', ['I']],
                ['Keyboard cheatsheet', ['?']],
                ['Close overlays', ['Esc']],
            ],
        },
        {
            title: 'Library',
            rows: [
                ['Density cinematic / cozy / compact', ['1', '2', '3']],
                ['Focus search', ['/']],
                ['Batch selection mode', ['B']],
                ['Theater mode', ['T']],
            ],
        },
        {
            title: 'Player',
            rows: [
                ['Play / pause', ['Space']],
                ['Seek back / forward', ['←', '→']],
                ['Slower / faster', ['[', ']']],
                ['Fullscreen', ['F']],
                ['Picture-in-picture', ['P']],
                ['Split screen', ['S']],
            ],
        },
        {
            title: 'Discovery review',
            rows: [
                ['Approve', ['→']],
                ['Reject', ['←']],
                ['Preview', ['Space']],
                ['Exit review', ['Esc']],
            ],
        },
    ];

    const keys = (() => {
        let root;

        function mount() {
            const grid = h('div', { class: 'nx-keys-grid' },
                KEYS_GROUPS.map((g) =>
                    h('div', { class: 'nx-keys-group' }, [
                        h('h4', { text: g.title }),
                        ...g.rows.map(([label, combo]) =>
                            h('div', { class: 'nx-keys-row' }, [
                                h('span', { text: label }),
                                h('span', { class: 'nx-keys-combo' },
                                    combo.map((k) => h('kbd', { text: k }))
                                ),
                            ])
                        ),
                    ])
                )
            );
            root = h('div', { class: 'nx-keys-scrim', role: 'dialog', 'aria-label': 'Keyboard Shortcuts' }, [
                h('div', { class: 'nx-keys-card' }, [
                    h('div', { class: 'nx-keys-sub', text: 'Reference' }),
                    h('h2', { class: 'nx-keys-title', text: 'Keyboard shortcuts' }),
                    grid,
                ]),
            ]);
            root.addEventListener('click', (e) => {
                if (e.target === root) close();
            });
            document.body.appendChild(root);
        }

        function open() {
            if (!root) mount();
            root.dataset.open = 'true';
        }

        function close() {
            if (root) root.dataset.open = 'false';
        }

        function toggle() {
            if (root?.dataset.open === 'true') close();
            else open();
        }

        return { open, close, toggle };
    })();

    // ============================================================
    // 4) PERSISTENT MINI-PLAYER
    // ============================================================
    const mini = (() => {
        let root, slot, titleEl, hostVideo = null, placeholder = null, io = null;

        function mount() {
            root = h('div', { class: 'nx-mini', 'aria-label': 'Mini player' }, [
                slot = h('div', { class: 'nx-mini-slot' }),
                h('div', { class: 'nx-mini-bar' }, [
                    titleEl = h('span', { class: 'nx-mini-title', text: 'Now playing' }),
                    h('button', {
                        class: 'nx-mini-btn',
                        'aria-label': 'Restore to page',
                        onclick: restore,
                    }, [icon('film')]),
                    h('button', {
                        class: 'nx-mini-btn',
                        'aria-label': 'Close',
                        onclick: close,
                    }, [icon('close')]),
                ]),
            ]);
            document.body.appendChild(root);
        }

        function findActiveVideo() {
            const candidates = $$('video');
            for (const v of candidates) {
                const r = v.getBoundingClientRect();
                if (r.width > 0 && !v.paused && !v.ended) return v;
            }
            return null;
        }

        function attach(video) {
            if (!root) mount();
            if (!video) return false;
            if (hostVideo === video) return true;

            release();

            hostVideo = video;
            placeholder = document.createComment('nx-mini-placeholder');
            video.parentNode.insertBefore(placeholder, video);
            slot.appendChild(video);

            const t = document.title || video.getAttribute('data-title') || 'Now playing';
            titleEl.textContent = t.length > 50 ? t.slice(0, 50) + '…' : t;
            root.dataset.open = 'true';
            return true;
        }

        function release() {
            if (hostVideo && placeholder && placeholder.parentNode) {
                placeholder.parentNode.insertBefore(hostVideo, placeholder);
                placeholder.parentNode.removeChild(placeholder);
            }
            hostVideo = null;
            placeholder = null;
        }

        function close() {
            if (root) root.dataset.open = 'false';
            release();
        }

        function restore() {
            release();
            if (root) root.dataset.open = 'false';
        }

        function toggle() {
            if (!root) mount();
            if (root.dataset.open === 'true') { close(); return; }
            const v = findActiveVideo();
            if (v) attach(v);
        }

        function observe() {
            if (!('IntersectionObserver' in window)) return;
            io = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    const v = entry.target;
                    if (!(v instanceof HTMLVideoElement)) return;
                    if (entry.isIntersecting) {
                        if (hostVideo === v) restore();
                    } else if (!v.paused && !v.ended && v.currentTime > 0) {
                        const main = v.closest('.player-container, .main-player, .video-player');
                        if (main) attach(v);
                    }
                });
            }, { threshold: 0.15 });

            const scan = () => {
                $$('video').forEach((v) => {
                    if (!v.dataset.nxObserved) {
                        v.dataset.nxObserved = '1';
                        io.observe(v);
                    }
                });
            };
            scan();
            new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
        }

        return { open: () => { mount(); const v = findActiveVideo(); if (v) attach(v); }, close, toggle, observe };
    })();

    // ============================================================
    // 5) AMBIENT GLOW (dominant color sampler)
    // ============================================================
    const ambient = (() => {
        const cache = new WeakMap();

        function sample(img) {
            if (cache.has(img)) return Promise.resolve(cache.get(img));
            return new Promise((resolve) => {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = 16;
                    canvas.height = 9;
                    const ctx = canvas.getContext('2d', { willReadFrequently: true });
                    ctx.drawImage(img, 0, 0, 16, 9);
                    const data = ctx.getImageData(0, 0, 16, 9).data;
                    let r = 0, g = 0, b = 0, n = 0;
                    for (let i = 0; i < data.length; i += 4) {
                        r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
                    }
                    r = (r / n) | 0; g = (g / n) | 0; b = (b / n) | 0;
                    const rgba = `rgba(${r}, ${g}, ${b}, 0.45)`;
                    cache.set(img, rgba);
                    resolve(rgba);
                } catch (e) {
                    resolve(null);
                }
            });
        }

        function applyTo(container, color) {
            if (!container || !color) return;
            container.style.setProperty('--nx-glow-color', color);
        }

        function bindPlayer() {
            const container = $('.player-container, .main-player');
            if (!container) return;
            const video = container.querySelector('video');
            if (!video) return;
            const poster = video.poster;
            if (poster) {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = () => sample(img).then((c) => applyTo(container, c));
                img.src = poster;
            }
            video.addEventListener('loadeddata', () => {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = 16;
                    canvas.height = 9;
                    const ctx = canvas.getContext('2d', { willReadFrequently: true });
                    ctx.drawImage(video, 0, 0, 16, 9);
                    const data = ctx.getImageData(0, 0, 16, 9).data;
                    let r = 0, g = 0, b = 0, n = 0;
                    for (let i = 0; i < data.length; i += 4) {
                        r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
                    }
                    r = (r / n) | 0; g = (g / n) | 0; b = (b / n) | 0;
                    applyTo(container, `rgba(${r}, ${g}, ${b}, 0.5)`);
                } catch (e) { /* cross-origin fail — silently noop */ }
            }, { once: false });
        }

        return { bindPlayer };
    })();

    // ============================================================
    // 6) IMPORT DRAWER
    // ============================================================
    const drawer = (() => {
        let root, scrim, urlInput, detectBadge, tagsInput, feedback;

        function mount() {
            scrim = h('div', { class: 'nx-drawer-scrim', onclick: close });
            urlInput = h('input', {
                class: 'nx-drawer-input',
                type: 'url',
                placeholder: 'https://…',
                autocomplete: 'off',
                spellcheck: 'false',
            });
            urlInput.addEventListener('input', onUrlChange);
            urlInput.addEventListener('paste', () => setTimeout(onUrlChange, 0));
            detectBadge = h('span', { class: 'nx-detect-chip is-unknown', text: 'detecting…' });
            tagsInput = h('input', {
                class: 'nx-drawer-input',
                type: 'text',
                placeholder: 'optional tags, comma separated',
            });
            feedback = h('div', { class: 'nx-drawer-note', text: '' });

            root = h('aside', { class: 'nx-drawer', role: 'dialog', 'aria-label': 'Import' }, [
                h('div', { class: 'nx-drawer-head' }, [
                    h('button', { class: 'nx-drawer-close', 'aria-label': 'Close', onclick: close }, [icon('close')]),
                    h('span', { class: 'nx-drawer-eyebrow', text: 'Unified import' }),
                    h('h2', { class: 'nx-drawer-title', text: 'Pull anything in' }),
                ]),
                h('div', { class: 'nx-drawer-body' }, [
                    h('div', { class: 'nx-drawer-field' }, [
                        h('label', { text: 'Source URL or playlist' }),
                        urlInput,
                        h('div', { style: 'margin-top:10px;display:flex;align-items:center;gap:10px;' }, [detectBadge]),
                    ]),
                    h('div', { class: 'nx-drawer-field' }, [
                        h('label', { text: 'Tags (optional)' }),
                        tagsInput,
                    ]),
                    h('div', { class: 'nx-drawer-note', html:
                        'The drawer delegates to the existing <code>/api/v1/import</code> pipeline. Source-specific options ' +
                        '(cookies, quality, depth) stay inside the dedicated modals for now — this is the fast lane for ' +
                        'single URLs and paste-from-clipboard flows.' }),
                    feedback,
                ]),
                h('div', { class: 'nx-drawer-foot' }, [
                    h('button', { class: 'nx-btn nx-btn-ghost', onclick: close, text: 'Cancel' }),
                    h('button', { class: 'nx-btn nx-btn-primary', onclick: submit }, [
                        icon('download'),
                        h('span', { text: 'Queue import' }),
                    ]),
                ]),
            ]);

            document.body.appendChild(scrim);
            document.body.appendChild(root);
        }

        function onUrlChange() {
            const v = urlInput.value.trim();
            if (!v) { detectBadge.className = 'nx-detect-chip is-unknown'; detectBadge.textContent = 'waiting for url'; return; }
            const src = detectSource(v);
            if (src) {
                detectBadge.className = 'nx-detect-chip';
                detectBadge.style.setProperty('--nx-src', `var(${src.token})`);
                detectBadge.style.setProperty('background', `color-mix(in srgb, var(${src.token}) 18%, transparent)`);
                detectBadge.style.setProperty('border-color', `color-mix(in srgb, var(${src.token}) 60%, transparent)`);
                detectBadge.style.setProperty('color', `color-mix(in srgb, var(${src.token}) 85%, white)`);
                detectBadge.textContent = `detected · ${src.name}`;
            } else {
                detectBadge.className = 'nx-detect-chip is-unknown';
                detectBadge.textContent = 'generic url · will use yt-dlp';
            }
        }

        function open(prefillUrl) {
            if (!root) mount();
            scrim.dataset.open = 'true';
            root.dataset.open = 'true';
            feedback.textContent = '';
            if (prefillUrl) { urlInput.value = prefillUrl; onUrlChange(); }
            requestAnimationFrame(() => urlInput.focus());
        }

        function close() {
            if (scrim) scrim.dataset.open = 'false';
            if (root) root.dataset.open = 'false';
        }

        async function submit() {
            const url = urlInput.value.trim();
            if (!url) { feedback.textContent = 'Paste a URL first.'; return; }
            feedback.textContent = 'Queuing…';
            try {
                const tags = tagsInput.value
                    .split(',').map((t) => t.trim()).filter(Boolean);
                // Tries several common endpoints — first success wins.
                const payloads = [
                    { path: '/api/v1/import', body: { url, tags } },
                    { path: '/api/v1/import_url', body: { url, tags } },
                    { path: '/api/v1/videos/import', body: { url, tags } },
                ];
                let ok = false, msg = 'No endpoint accepted the import.';
                for (const p of payloads) {
                    try {
                        const res = await fetch(p.path, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(p.body),
                        });
                        if (res.ok) { ok = true; msg = `Queued via ${p.path}`; break; }
                        if (res.status !== 404 && res.status !== 405) {
                            const t = await res.text().catch(() => '');
                            msg = `Server said ${res.status}: ${t.slice(0, 120)}`;
                        }
                    } catch (e) { msg = e.message || 'Network error'; }
                }
                feedback.textContent = msg;
                if (ok) setTimeout(close, 900);
            } catch (e) {
                feedback.textContent = e.message || 'Unexpected error';
            }
        }

        return { open, close };
    })();

    // ============================================================
    // 7) DENSITY TOGGLE
    // ============================================================
    const density = (() => {
        const KEY = 'nx.density';
        function set(mode) {
            if (!['cinematic', 'cozy', 'compact'].includes(mode)) return;
            document.body.dataset.density = mode;
            try { localStorage.setItem(KEY, mode); } catch (e) { }
            $$('.nx-density button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
        }
        function init() {
            let mode = 'cozy';
            try { mode = localStorage.getItem(KEY) || 'cozy'; } catch (e) { }
            set(mode);
        }
        return { set, init };
    })();

    // ============================================================
    // 8) TRIGGER PILL & OPTIONAL DENSITY SWITCHER IN TOP BAR
    // ============================================================
    function mountTrigger() {
        const trigger = h('button', {
            class: 'nx-trigger',
            'aria-label': 'Open command palette',
            onclick: () => palette.open(),
        }, [
            icon('command'),
            h('span', { text: 'Command' }),
            h('span', { class: 'nx-palette-kbd', text: 'Ctrl Shift P' }),
        ]);
        document.body.appendChild(trigger);
    }

    function mountDensitySwitcher() {
        // Graceful-attach to the top bar if it exists.
        const host = $('.top-bar .view-switcher, .top-bar') ;
        if (!host) return;
        if ($('.nx-density')) return;
        const group = h('div', { class: 'nx-density', role: 'group', 'aria-label': 'Grid density' }, [
            h('button', { dataset: { mode: 'cinematic' }, onclick: () => density.set('cinematic'), text: 'Cinema' }),
            h('button', { dataset: { mode: 'cozy' }, onclick: () => density.set('cozy'), text: 'Cozy' }),
            h('button', { dataset: { mode: 'compact' }, onclick: () => density.set('compact'), text: 'Compact' }),
        ]);
        host.appendChild(group);
        density.init();
    }

    // ============================================================
    // 9) GLOBAL KEY BINDINGS
    // ============================================================
    function bindKeys() {
        window.addEventListener('keydown', (e) => {
            if (isTypingTarget(e.target)) return;

            // Ctrl/Cmd + Shift + P → command palette
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'P' || e.key === 'p')) {
                e.preventDefault();
                palette.toggle();
                return;
            }

            // '?' → shortcuts
            if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                keys.toggle();
                return;
            }

            // 'i' → import drawer
            if (e.key === 'i' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                drawer.open();
                return;
            }

            // Density 1/2/3 (without modifiers)
            if (!e.ctrlKey && !e.metaKey && !e.altKey) {
                if (e.key === '1') { density.set('cinematic'); return; }
                if (e.key === '2') { density.set('cozy'); return; }
                if (e.key === '3') { density.set('compact'); return; }
            }

            // Esc — close any nx overlay.
            if (e.key === 'Escape') {
                palette.close();
                keys.close();
                drawer.close();
                if (window.NXShell?.swipe) window.NXShell.swipe.close();
            }
        }, { capture: false });
    }

    // ============================================================
    // 10) SWIPE REVIEW (lazy-built on /discovery/review)
    // ============================================================
    const swipe = (() => {
        let root, card, stage, progress, items = [], cursor = 0, onDecide = null;

        function mount() {
            root = h('div', { class: 'nx-swipe-scrim', role: 'dialog', 'aria-label': 'Review' }, [
                h('div', { class: 'nx-swipe-head' }, [
                    h('span', { text: 'Discovery · review mode' }),
                    h('button', { class: 'nx-btn nx-btn-ghost', onclick: close, text: 'Exit' }),
                ]),
                stage = h('div', { class: 'nx-swipe-stage' }),
                h('div', { class: 'nx-swipe-actions' }, [
                    h('button', { class: 'nx-swipe-action reject', 'aria-label': 'Reject', onclick: () => decide('reject') }, [icon('close')]),
                    h('button', { class: 'nx-swipe-action preview', 'aria-label': 'Preview', onclick: () => decide('preview') }, [icon('eye')]),
                    h('button', { class: 'nx-swipe-action approve', 'aria-label': 'Approve', onclick: () => decide('approve') }, [icon('check')]),
                ]),
                progress = h('div', { class: 'nx-swipe-progress', text: '' }),
            ]);
            root.addEventListener('keydown', onKey);
            document.body.appendChild(root);
        }

        function open(list, handler) {
            if (!root) mount();
            items = list || [];
            cursor = 0;
            onDecide = handler;
            root.dataset.open = 'true';
            render();
            root.focus();
        }

        function close() {
            if (root) root.dataset.open = 'false';
        }

        function current() { return items[cursor]; }

        function render() {
            stage.innerHTML = '';
            const item = current();
            if (!item) {
                stage.appendChild(h('div', { class: 'nx-swipe-meta' }, [
                    h('h3', { text: 'All done' }),
                    h('p', { text: `Reviewed ${items.length} items` }),
                ]));
                progress.textContent = '';
                return;
            }
            card = h('div', { class: 'nx-swipe-card' }, [
                h('div', {
                    class: 'nx-swipe-thumb',
                    style: `background-image:url(${item.thumbnail || item.thumbnail_url || ''})`,
                }),
                h('div', { class: 'nx-swipe-meta' }, [
                    h('h3', { text: item.title || 'Untitled' }),
                    h('p', { text: (item.source || detectSource(item.source_url || '')?.name || 'unknown') + ' · ' + (item.duration_display || '') }),
                ]),
            ]);
            stage.appendChild(card);
            progress.textContent = `${cursor + 1} / ${items.length}`;
        }

        function decide(kind) {
            const item = current();
            if (!item) return;
            if (kind === 'preview') {
                window.open(item.source_url || item.url || '', '_blank', 'noopener');
                return;
            }
            if (card) card.dataset.state = kind;
            onDecide?.(item, kind);
            setTimeout(() => {
                cursor++;
                render();
            }, 220);
        }

        function onKey(e) {
            if (e.key === 'ArrowRight') { e.preventDefault(); decide('approve'); }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); decide('reject'); }
            else if (e.key === ' ') { e.preventDefault(); decide('preview'); }
            else if (e.key === 'Escape') { close(); }
        }

        return { open, close };
    })();

    // ============================================================
    // 11) PUBLIC INTERFACE
    // ============================================================
    const NXShell = {
        palette,
        keys,
        mini,
        drawer,
        density,
        swipe,
        ambient,
        annotateAllCards,
    };
    window.NXShell = NXShell;

    // ============================================================
    // 12) BOOT
    // ============================================================
    function boot() {
        mountTrigger();
        mountDensitySwitcher();
        density.init();
        bindKeys();
        mini.observe();
        ambient.bindPlayer();
        annotateAllCards();

        const obs = new MutationObserver((muts) => {
            let anyCard = false;
            for (const m of muts) {
                for (const n of m.addedNodes) {
                    if (!(n instanceof HTMLElement)) continue;
                    if (n.classList?.contains('v-card') || n.querySelector?.('.v-card')) anyCard = true;
                    if (n.classList?.contains('top-bar') || n.querySelector?.('.top-bar')) mountDensitySwitcher();
                }
            }
            if (anyCard) annotateAllCards();
        });
        obs.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
