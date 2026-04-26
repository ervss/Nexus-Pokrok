# Pornhub Video Detection & Import Implementation

## Overview
The extension has been successfully updated to support **Pornhub** video detection and import, matching the quality and functionality of the existing GoFile and Eporner implementations.

## What Was Implemented

### 1. **Pornhub Page Detection**
- Automatically detects when you're on any Pornhub page (search results, categories, etc.)
- Shows the Quantum Explorer interface with Turbo controls

### 2. **Video Metadata Extraction**
The scraper extracts comprehensive metadata from each video:
- ✅ **Title** - Full video title
- ✅ **Thumbnail** - High-quality preview image
- ✅ **Duration** - Video length (e.g., "12:34")
- ✅ **Quality** - Resolution badge (4K, 1440p, 1080p, 720p, HD, SD)
- ✅ **Rating** - User rating percentage (e.g., 85%)
- ✅ **Views** - View count (formatted as 1.2M, 500K, etc.)
- ✅ **URL** - Direct link to the video page

### 3. **Turbo Mode Support**
- **Normal Mode**: Scrapes current page only
- **Turbo Mode**: Scrapes 4 pages simultaneously for bulk collection
- **Auto-Send**: Automatically imports to dashboard when enabled

### 4. **Import Process**
The import process works exactly like GoFile and Eporner:
1. Videos are displayed in a grid with thumbnails
2. Select videos individually or use "Select All"
3. Click "Import" to send to your Nexus dashboard
4. Videos are sent to `/api/v1/import/bulk` endpoint

## How to Use

### Step 1: Load the Extension
1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the folder: `C:\Users\Peto\Desktop\PICA\Nexus-Future-W-main\gofile_explorer_extension`

### Step 2: Navigate to Pornhub
Go to any Pornhub page with video listings:
- Search results: `https://cz.pornhub.com/video/search?search=daisy+lee`
- Categories: `https://cz.pornhub.com/categories`
- Channels: `https://cz.pornhub.com/channels`
- Any page with video thumbnails

### Step 3: Open the Extension
1. Click the extension icon in Chrome toolbar
2. The extension will automatically detect Pornhub
3. You'll see "Pornhub Explorer" at the top

### Step 4: Configure Options
- **Turbo Mode**: Enable to scrape 4 pages at once
- **Auto-Send to Dashboard**: Enable to automatically import all videos

### Step 5: Select & Import
1. Browse the scraped videos in the grid
2. Click videos to select them (they'll highlight)
3. Use "Vybrať všetko" to select all
4. Click "Importovať" to send to your dashboard

## Technical Details

### Selectors Used
The scraper uses multiple CSS selectors to ensure compatibility:
```javascript
// Container selectors
'.pcVideoListItem, .videoBox, li[data-video-vkey]'

// Link selectors
'a[href*="/view_video.php"], a.linkVideoThumb, a[data-title]'

// Thumbnail selectors
'img.thumb, img[data-src], img[data-thumb_url]'

// Duration selector
'.duration, .marker-overlays .duration'

// Quality selectors
'.hd, .videoHD, .marker-overlays .hd'

// Rating selectors
'.value, .percent, .rating-container .value'

// Views selectors
'.views, .videoDetailsBlock .views var'
```

### Pagination Logic
For Turbo Mode, the scraper:
1. Extracts videos from the current page
2. Fetches pages 2, 3, and 4 using the `?page=N` parameter
3. Preserves existing search parameters (search query, filters, etc.)
4. Combines all results into a single grid

### Data Structure
Each video object contains:
```javascript
{
    id: "https://cz.pornhub.com/view_video.php?viewkey=...",
    title: "Video Title",
    url: "https://cz.pornhub.com/view_video.php?viewkey=...",
    source_url: "https://cz.pornhub.com/view_video.php?viewkey=...",
    thumbnail: "https://...",
    rating: 85,
    views: 1500000,
    duration: "12:34",
    quality: "1080p",
    size: 0
}
```

## Files Modified

### 1. `popup.js`
- Added `handlePornhubScraping()` function (lines 320-494)
- Added Pornhub detection in DOMContentLoaded (line 67)
- Updated supported sites message

### 2. `manifest.json`
- Updated name to "Quantum Explorer - Multi-Platform Video Importer"
- Updated version to 2.0
- Added `"https://*.pornhub.com/*"` to host_permissions
- Updated description to include Pornhub

## Comparison with GoFile & Eporner

| Feature | GoFile | Eporner | Pornhub |
|---------|--------|---------|---------|
| Detection | ✅ | ✅ | ✅ |
| Metadata Extraction | ✅ | ✅ | ✅ |
| Turbo Mode | ❌ | ✅ | ✅ |
| Auto-Send | ❌ | ✅ | ✅ |
| Multi-page Scraping | ❌ | ✅ | ✅ |
| Rating Display | ❌ | ✅ | ✅ |
| Views Display | ❌ | ✅ | ✅ |
| Quality Detection | ✅ | ✅ | ✅ |
| Duration Display | ✅ | ✅ | ✅ |

## Testing Checklist

- [x] Extension loads without errors
- [x] Pornhub pages are detected correctly
- [x] Video metadata is extracted accurately
- [x] Thumbnails display properly
- [x] Selection works (individual & select all)
- [x] Import sends data to dashboard
- [x] Turbo mode scrapes multiple pages
- [x] Auto-send works when enabled
- [x] Error handling works for failed requests

## Next Steps

If you want to enhance the implementation further:

1. **Add content script** for Pornhub (like GoFile has) for advanced features
2. **Extract video download URLs** directly (requires more complex scraping)
3. **Add filters** for quality, rating, views
4. **Support model/channel pages** with different layouts
5. **Add preview on hover** like the main dashboard

## Troubleshooting

### No videos found
- Make sure you're on a page with video listings
- Check browser console for errors (F12)
- Try refreshing the page

### Import fails
- Ensure your Nexus dashboard is running
- Check that it's accessible on one of the ports: 8000-8005
- Verify the `/api/v1/import/bulk` endpoint is working

### Thumbnails not loading
- Pornhub uses lazy-loading for images
- The scraper handles `data-src` and `data-thumb_url` attributes
- Some thumbnails may require scrolling on the page first

---

**Implementation Date**: 2026-01-29  
**Version**: 2.0  
**Status**: ✅ Complete and Working
