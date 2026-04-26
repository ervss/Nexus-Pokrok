# 🧪 Testing Guide - Pornhub Integration

## Quick Test Checklist

### ✅ Pre-Testing Setup
- [ ] Extension loaded in Chrome (`chrome://extensions/`)
- [ ] Developer mode enabled
- [ ] No console errors on extension load
- [ ] Nexus dashboard running (port 8000-8005)

---

## 🎯 Test Case 1: Basic Pornhub Detection

### Steps:
1. Navigate to: `https://cz.pornhub.com/video/search?search=daisy+lee`
2. Click the extension icon
3. Wait for scraper to load

### Expected Results:
- ✅ Extension popup opens
- ✅ Shows "Pornhub Explorer" title
- ✅ Turbo controls are visible
- ✅ Video grid displays with thumbnails
- ✅ Stats show "Nájdených X videí"

### Console Checks:
```
✅ "Pornhub page detected. Starting scraper."
✅ "Starting Pornhub scraping for tab: [ID]"
✅ "Scraped X videos from Pornhub."
```

---

## 🎯 Test Case 2: Metadata Extraction

### Steps:
1. Open extension on Pornhub search results
2. Inspect first 3 videos in the grid

### Verify Each Video Has:
- [ ] **Title** - Readable, not "Pornhub Video"
- [ ] **Thumbnail** - Loads correctly (not broken image)
- [ ] **Duration** - Format: "MM:SS" or "H:MM:SS"
- [ ] **Quality Badge** - Shows: 4K, 1080p, 720p, HD, or SD
- [ ] **Rating** - Shows percentage (e.g., "★ 85%")
- [ ] **Views** - Formatted (e.g., "👁 1.2M")

### Sample Video Object (Console):
```javascript
{
  id: "https://cz.pornhub.com/view_video.php?viewkey=...",
  title: "Daisy Lee Video Title",
  url: "https://cz.pornhub.com/view_video.php?viewkey=...",
  thumbnail: "https://...",
  rating: 85,
  views: 1500000,
  duration: "12:34",
  quality: "1080p",
  size: 0
}
```

---

## 🎯 Test Case 3: Video Selection

### Steps:
1. Click on individual video cards
2. Click "Vybrať všetko" button
3. Click individual videos again to deselect

### Expected Results:
- [ ] Clicked videos highlight with border
- [ ] Stats update: "Vybraných X"
- [ ] "Select All" selects all visible videos
- [ ] "Select All" again deselects all
- [ ] Import button shows count: "Importovať (X)"
- [ ] Import button disabled when 0 selected

---

## 🎯 Test Case 4: Search & Filter

### Steps:
1. Type "daisy" in search box
2. Change sort to "Name"
3. Change sort to "Size (Descending)"

### Expected Results:
- [ ] Grid updates in real-time
- [ ] Only matching videos shown
- [ ] Videos sorted correctly
- [ ] Selection persists through filtering

---

## 🎯 Test Case 5: Normal Import

### Steps:
1. Select 3-5 videos
2. Click "Importovať (X)" button
3. Watch for status changes

### Expected Results:
- [ ] Button shows "Importujem..."
- [ ] Button disabled during import
- [ ] Network request to `/api/v1/import/bulk`
- [ ] Button shows "Hotovo!" on success
- [ ] Extension closes after 1 second
- [ ] Videos appear in dashboard

### Network Payload:
```json
{
  "batch_name": "Explorer: Pornhub Explorer",
  "videos": [
    {
      "title": "Video Title",
      "url": "https://...",
      "source_url": "https://...",
      "thumbnail": "https://...",
      "filesize": 0,
      "duration": "12:34"
    }
  ]
}
```

---

## 🎯 Test Case 6: Turbo Mode (Single Page)

### Steps:
1. Navigate to Pornhub search results
2. Open extension
3. Enable "Turbo Mode" checkbox
4. Wait for scraping to complete

### Expected Results:
- [ ] Stats show "Turbo mode: Scraping 4 pages..."
- [ ] Title shows "Pornhub Explorer (Turbo)"
- [ ] More videos than normal mode
- [ ] Videos from pages 1-4 combined
- [ ] No duplicate videos

### Console Checks:
```
✅ "Pornhub scrape settings: turbo=true, autoSend=false, pageLimit=4"
✅ No "Failed to fetch Pornhub page" errors
```

---

## 🎯 Test Case 7: Auto-Send Mode

### Steps:
1. Navigate to Pornhub search results
2. Open extension
3. Enable both "Turbo Mode" and "Auto-Send to Dashboard"
4. Wait for completion

### Expected Results:
- [ ] Scraping completes
- [ ] Stats show "| Sending to DB..."
- [ ] Videos automatically sent to dashboard
- [ ] No manual import needed
- [ ] Videos appear in dashboard immediately

### Console Checks:
```
✅ "Auto-sending to dashboard."
✅ POST request to /api/v1/import/bulk
✅ No "Turbo auto-send failed" errors
```

---

## 🎯 Test Case 8: Multi-Page Pagination

### Steps:
1. Navigate to: `https://cz.pornhub.com/video/search?search=popular`
2. Enable Turbo Mode
3. Open browser DevTools → Network tab
4. Trigger scraping

### Expected Results:
- [ ] 3 additional fetch requests for pages 2, 3, 4
- [ ] URLs contain `?page=2`, `?page=3`, `?page=4`
- [ ] Search parameters preserved in URLs
- [ ] All pages return 200 OK
- [ ] Results combined correctly

### Sample URLs:
```
https://cz.pornhub.com/video/search?search=popular&page=2
https://cz.pornhub.com/video/search?search=popular&page=3
https://cz.pornhub.com/video/search?search=popular&page=4
```

---

## 🎯 Test Case 9: Different Pornhub Pages

Test on various page types to ensure selector compatibility:

### A) Search Results
- URL: `https://cz.pornhub.com/video/search?search=query`
- [ ] Videos load correctly
- [ ] Metadata extracted

### B) Category Page
- URL: `https://cz.pornhub.com/categories/amateur`
- [ ] Videos load correctly
- [ ] Metadata extracted

### C) Trending Page
- URL: `https://cz.pornhub.com/video?o=tr`
- [ ] Videos load correctly
- [ ] Metadata extracted

### D) Model Page
- URL: `https://cz.pornhub.com/model/[name]`
- [ ] Videos load correctly
- [ ] Metadata extracted

---

## 🎯 Test Case 10: Error Handling

### A) No Dashboard Running
1. Stop Nexus dashboard
2. Try to import videos
3. **Expected**: Import fails gracefully, button shows "Chyba!"

### B) No Videos on Page
1. Navigate to empty Pornhub page
2. Open extension
3. **Expected**: Shows "Žiadne videá sa nenašli."

### C) Network Error (Turbo)
1. Enable Turbo Mode
2. Disconnect internet mid-scrape
3. **Expected**: Partial results shown, no crash

### D) Invalid Page
1. Navigate to Pornhub homepage (no videos)
2. Open extension
3. **Expected**: Shows 0 videos, no errors

---

## 🎯 Test Case 11: Cross-Platform Compatibility

### Test All Three Platforms:

#### GoFile
- URL: `https://gofile.io/d/[folder_id]`
- [ ] Detection works
- [ ] No Turbo controls shown
- [ ] Import works

#### Eporner
- URL: `https://www.eporner.com/category/amateur/`
- [ ] Detection works
- [ ] Turbo controls shown
- [ ] Import works

#### Pornhub
- URL: `https://cz.pornhub.com/video/search?search=test`
- [ ] Detection works
- [ ] Turbo controls shown
- [ ] Import works

### Verify:
- [ ] Switching between platforms works
- [ ] No cross-contamination of data
- [ ] Each platform uses correct scraper

---

## 🎯 Test Case 12: Performance & Memory

### Steps:
1. Open extension on Pornhub
2. Enable Turbo Mode (4 pages)
3. Monitor Chrome Task Manager

### Benchmarks:
- [ ] Scraping completes in < 10 seconds
- [ ] Memory usage < 100MB
- [ ] No memory leaks after closing
- [ ] CPU usage returns to normal

### Console Performance:
```javascript
// Check in DevTools Console
performance.measure('scrape-time');
// Should be < 10000ms for 4 pages
```

---

## 🎯 Test Case 13: UI/UX Polish

### Visual Checks:
- [ ] Grid layout is responsive
- [ ] Thumbnails maintain aspect ratio
- [ ] Text doesn't overflow containers
- [ ] Badges (quality, rating) are visible
- [ ] Selection highlight is clear
- [ ] Buttons have hover states
- [ ] Loading spinner shows during scrape

### Interaction Checks:
- [ ] Clicks are responsive (< 100ms)
- [ ] Scrolling is smooth
- [ ] Search input has focus on type
- [ ] Keyboard navigation works (Tab)

---

## 🎯 Test Case 14: Edge Cases

### A) Very Long Titles
- [ ] Titles truncate with ellipsis
- [ ] Tooltip shows full title on hover

### B) Missing Metadata
- [ ] Videos without duration show empty string
- [ ] Videos without rating show 0 or hide badge
- [ ] Default quality is "SD"

### C) Special Characters in Title
- [ ] Titles with quotes, apostrophes render correctly
- [ ] Unicode characters (emoji) display properly

### D) Large Result Sets
- [ ] 100+ videos render without lag
- [ ] Selection of all 100+ works
- [ ] Import of 100+ completes

---

## 🐛 Known Issues & Workarounds

### Issue 1: Lazy-Loaded Thumbnails
**Problem**: Some thumbnails don't load immediately  
**Workaround**: Scroll down the page before opening extension

### Issue 2: Rate Limiting
**Problem**: Too many rapid requests may trigger Cloudflare  
**Workaround**: Use Turbo Mode sparingly, wait between scrapes

### Issue 3: Dynamic Content
**Problem**: Some pages load content via JavaScript  
**Workaround**: Wait for page to fully load before opening extension

---

## 📊 Success Criteria

### Minimum Viable:
- ✅ Detects Pornhub pages
- ✅ Extracts at least: title, URL, thumbnail
- ✅ Selection works
- ✅ Import sends to dashboard

### Full Feature Set:
- ✅ All metadata extracted (duration, quality, rating, views)
- ✅ Turbo Mode works (4 pages)
- ✅ Auto-Send works
- ✅ No console errors
- ✅ Performance < 10s for 4 pages

### Production Ready:
- ✅ All test cases pass
- ✅ Error handling graceful
- ✅ UI polished
- ✅ Documentation complete

---

## 🚀 Quick Test Script

Run this in the browser console after opening the extension:

```javascript
// Verify allVideos array is populated
console.log('Total videos:', allVideos.length);

// Check first video structure
console.log('Sample video:', allVideos[0]);

// Verify required fields
const requiredFields = ['id', 'title', 'url', 'thumbnail', 'duration', 'quality'];
const hasAllFields = requiredFields.every(field => 
  allVideos[0].hasOwnProperty(field)
);
console.log('Has all required fields:', hasAllFields);

// Check for duplicates
const uniqueIds = new Set(allVideos.map(v => v.id));
console.log('Duplicates found:', allVideos.length !== uniqueIds.size);
```

---

## 📝 Test Report Template

```markdown
## Test Report - [Date]

**Tester**: [Name]
**Version**: 2.0
**Platform**: Pornhub
**Browser**: Chrome [Version]

### Results:
- [ ] Basic Detection: PASS/FAIL
- [ ] Metadata Extraction: PASS/FAIL
- [ ] Selection: PASS/FAIL
- [ ] Import: PASS/FAIL
- [ ] Turbo Mode: PASS/FAIL
- [ ] Auto-Send: PASS/FAIL

### Issues Found:
1. [Description]
2. [Description]

### Notes:
[Additional observations]
```

---

**Happy Testing! 🎉**
