# 🚀 Quantum Explorer - Multi-Platform Video Importer

<div align="center">

![Version](https://img.shields.io/badge/version-2.0-purple)
![Chrome](https://img.shields.io/badge/Chrome-Extension-green)
![Status](https://img.shields.io/badge/status-Active-success)

**Premium bulk video importer for GoFile, Eporner, and Pornhub**

</div>

---

## 📋 Overview

Quantum Explorer is a powerful Chrome extension that enables seamless video discovery, selection, and bulk import from multiple adult content platforms directly into your Nexus dashboard. Built with performance and user experience in mind.

## ✨ Features

### 🎯 Multi-Platform Support
- **GoFile** - Direct API integration with VIP account support
- **Eporner** - Advanced DOM scraping with rating & view metrics
- **Pornhub** - Comprehensive metadata extraction with quality detection

### ⚡ Turbo Mode
- Scrape up to **4 pages simultaneously**
- Automatic pagination handling
- Preserves search filters and parameters
- Progress indicators

### 🎨 Rich Metadata Extraction
- **Title** - Full video titles
- **Thumbnails** - High-quality preview images
- **Duration** - Formatted video length
- **Quality** - Resolution badges (4K, 1440p, 1080p, 720p, HD)
- **Rating** - User rating percentages
- **Views** - Formatted view counts (1.2M, 500K, etc.)
- **File Size** - For GoFile videos

### 🔄 Smart Import System
- Visual grid selection interface
- Individual or bulk selection
- One-click import to dashboard
- Auto-send mode for hands-free operation
- Real-time status updates

## 🛠️ Installation

### Step 1: Download
Clone or download this repository to your local machine.

### Step 2: Load Extension
1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in top-right corner)
3. Click **Load unpacked**
4. Select the extension folder

### Step 3: Verify
You should see "Quantum Explorer - Multi-Platform Video Importer" in your extensions list.

## 📖 Usage Guide

### For Pornhub

1. **Navigate** to any Pornhub page with video listings:
   - Search: `https://pornhub.com/video/search?search=query`
   - Categories: `https://pornhub.com/categories`
   - Channels: `https://pornhub.com/channels`

2. **Click** the extension icon in your Chrome toolbar

3. **Configure** (optional):
   - ✅ Enable **Turbo Mode** to scrape 4 pages
   - ✅ Enable **Auto-Send** to import automatically

4. **Select** videos from the grid:
   - Click individual videos to select
   - Use "Vybrať všetko" for bulk selection

5. **Import** to your dashboard:
   - Click "Importovať (X)" button
   - Videos are sent to your Nexus dashboard

### For Eporner

Same workflow as Pornhub - navigate to any Eporner listing page and follow the same steps.

### For Archivebate

Navigate to an Archivebate profile/listing page or a single `archivebate.com/watch/...` video, then use the same grid selection and import flow. Turbo mode scans additional `?page=N` pages.

### For GoFile

1. Navigate to a GoFile folder: `https://gofile.io/d/FOLDER_ID`
2. Click the extension icon
3. Videos are automatically loaded from the API
4. Select and import as usual

**Note**: GoFile requires authentication for private folders. The extension will:
- First check for browser cookies (if you're logged in)
- Fall back to dashboard token if available

## 🎮 Controls & Options

### Main Controls
- **Search** - Filter videos by title
- **Sort** - Order by name, size (ascending/descending)
- **Select All** - Toggle selection for all visible videos
- **Import** - Send selected videos to dashboard
- **Copy to Profile** - (GoFile only) Copy files to your account

### Turbo Controls
- **Turbo Mode** - Enable multi-page scraping (4 pages)
- **Auto-Send to Dashboard** - Automatically import all scraped videos

## 🔧 Technical Details

### Architecture
```
Extension Structure:
├── manifest.json       # Extension configuration
├── popup.html          # Main UI
├── popup.js            # Core logic & scrapers
├── popup.css           # Styling
├── content.js          # GoFile API integration
└── icon.png            # Extension icon
```

### API Integration
The extension communicates with your Nexus dashboard via:
- **Endpoint**: `http://localhost:8000-8005/api/v1/import/bulk`
- **Method**: POST
- **Format**: JSON

### Data Flow
```
Page Detection → Scraper Selection → Metadata Extraction → 
Grid Display → User Selection → Bulk Import → Dashboard Storage
```

### Selectors (Pornhub)
```javascript
Containers: '.pcVideoListItem, .videoBox, li[data-video-vkey]'
Links: 'a[href*="/view_video.php"], a.linkVideoThumb'
Thumbnails: 'img.thumb, img[data-src], img[data-thumb_url]'
Duration: '.duration, .marker-overlays .duration'
Quality: '.hd, .videoHD, .marker-overlays .hd'
Rating: '.value, .percent, .rating-container .value'
Views: '.views, .videoDetailsBlock .views var'
```

## 📊 Performance

| Platform | Avg. Scrape Time | Videos/Page | Turbo Speed |
|----------|------------------|-------------|-------------|
| Pornhub  | ~2-3 seconds     | 20-32       | 4x faster   |
| Eporner  | ~2-3 seconds     | 24-36       | 4x faster   |
| Archivebate | ~2-4 seconds | Varies      | 4x faster   |
| GoFile   | ~1-2 seconds     | Unlimited   | N/A (API)   |

## 🐛 Troubleshooting

### No videos found
- ✅ Ensure you're on a page with video listings
- ✅ Check browser console (F12) for errors
- ✅ Try refreshing the page
- ✅ Disable other extensions that might interfere

### Import fails
- ✅ Verify Nexus dashboard is running
- ✅ Check dashboard is accessible on ports 8000-8005
- ✅ Ensure `/api/v1/import/bulk` endpoint is working
- ✅ Check browser console for network errors

### Thumbnails not loading
- ✅ Some sites use lazy-loading (scroll down first)
- ✅ Check if images are blocked by ad-blocker
- ✅ Verify host permissions in manifest.json

### GoFile "Permission Denied"
- ✅ Log into GoFile in your browser first
- ✅ Or configure GoFile token in dashboard settings
- ✅ Check if folder is password-protected (not supported yet)

## 🔒 Permissions Explained

| Permission | Purpose |
|------------|---------|
| `activeTab` | Read current tab URL to detect platform |
| `storage` | Save user preferences (turbo mode, etc.) |
| `scripting` | Inject scraping scripts into pages |
| `cookies` | Access GoFile authentication cookies |
| `host_permissions` | Access APIs and page content |

## 🚀 Future Enhancements

- [ ] Direct video download URL extraction
- [ ] Advanced filtering (quality, rating, views)
- [ ] Model/channel page support
- [ ] Video preview on hover
- [ ] Batch naming templates
- [ ] Export to CSV/JSON
- [ ] Dark/Light theme toggle
- [ ] Custom dashboard port configuration

## 📝 Changelog

### Version 2.0 (2026-01-29)
- ✅ Added Pornhub support
- ✅ Implemented comprehensive metadata extraction
- ✅ Added Turbo mode for Pornhub
- ✅ Updated extension name and branding
- ✅ Enhanced error handling

### Version 1.0
- Initial release with GoFile and Eporner support

## 🤝 Contributing

This is a private project, but suggestions are welcome!

## 📄 License

Private/Proprietary - For personal use only.

## 👨‍💻 Developer

Built with ❤️ for the Nexus Future W ecosystem.

---

<div align="center">

**Made for power users who demand efficiency**

</div>
