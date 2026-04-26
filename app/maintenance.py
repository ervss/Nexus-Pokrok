import logging
import os
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.database import Video
from app.duplicate_detector import compute_phash, hamming_distance
import re

def get_duplicates_by_name(db: Session):
    """Find videos with the same title"""
    # Group by title and count
    duplicates = db.query(
        Video.title, 
        func.count(Video.id).label('count')
    ).group_by(Video.title).having(func.count(Video.id) > 1).all()
    
    results = []
    for dup in duplicates:
        videos = db.query(Video).filter(Video.title == dup.title).all()
        results.append({
            "title": dup.title,
            "count": dup.count,
            "videos": [
                {
                    "id": v.id,
                    "height": v.height,
                    "width": v.width,
                    "duration": v.duration,
                    "status": v.status,
                    "batch": v.batch_name
                } for v in videos
            ]
        })
    return results

def get_duplicates_by_hash(db: Session, threshold: int = 5):
    """Find videos with similar phashes"""
    videos = db.query(Video).filter(Video.phash.isnot(None)).all()
    groups = []
    seen = set()
    
    for i, v1 in enumerate(videos):
        if v1.id in seen:
            continue
            
        group = [v1]
        for v2 in videos[i+1:]:
            if v2.id in seen:
                continue
            
            distance = hamming_distance(v1.phash, v2.phash)
            if distance <= threshold:
                group.append(v2)
                seen.add(v2.id)
        
        if len(group) > 1:
            groups.append({
                "representative": v1.title,
                "count": len(group),
                "videos": [
                    {
                        "id": v.id,
                        "title": v.title,
                        "height": v.height,
                        "width": v.width,
                        "duration": v.duration,
                        "status": v.status,
                        "batch": v.batch_name
                    } for v in group
                ]
            })
            seen.add(v1.id)
            
    return groups

def auto_resolve_duplicates(db: Session, type: str = "name"):
    """
    Automatically resolve duplicates by keeping the best quality one.
    Best quality = highest (height * width), then longest duration.
    """
    if type == "name":
        groups = get_duplicates_by_name(db)
    else:
        groups = get_duplicates_by_hash(db)
        
    resolved_count = 0
    deleted_count = 0
    
    for group in groups:
        videos = group['videos']
        # Sort by quality: resolution DESC, duration DESC
        videos.sort(key=lambda x: (x['height'] * x['width'], x['duration']), reverse=True)
        
        # Keep the first one, delete the rest
        to_keep = videos[0]
        to_delete = videos[1:]
        
        for v_meta in to_delete:
            v = db.query(Video).get(v_meta['id'])
            if v:
                # Delete thumbnail
                if v.thumbnail_path:
                    thumb_path = f"app{v.thumbnail_path.split('?')[0]}"
                    if os.path.exists(thumb_path):
                        try: os.remove(thumb_path)
                        except: pass
                
                db.delete(v)
                deleted_count += 1
        
        resolved_count += 1
        
    db.commit()
    res = {"resolved_groups": resolved_count, "deleted_videos": deleted_count}
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"Auto-resolved {resolved_count} {type} duplicate groups. Deleted {deleted_count} videos.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    return res

def cleanup_broken_links(db: Session, delete_permanently: bool = False):
    """Remove or mark videos that are broken and cannot be refreshed"""
    broken = db.query(Video).filter(Video.link_status == "broken").all()
    count = 0
    
    for v in broken:
        # If it has no source_url, it can't be refreshed
        if not v.source_url or delete_permanently:
            if v.thumbnail_path:
                thumb_path = f"app{v.thumbnail_path.split('?')[0]}"
                if os.path.exists(thumb_path):
                    try: os.remove(thumb_path)
                    except: pass
            db.delete(v)
            count += 1
            
    db.commit()
    res = {"deleted": count}
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"Cleanup complete. Removed {count} broken links.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    return res

def normalize_all_titles(db: Session):
    """Remove common junk from titles"""
    videos = db.query(Video).all()
    count = 0
    
    # Common patterns to remove
    patterns = [
        r"\[.*?\]",           # [text]
        r"\(.*?\)",           # (text)
        r"www\..*?\.(com|net|org|tv)", # www.site.com
        r"\.(mp4|mkv|avi|webm|mov)$", # extensions
        r"^\d+\s*-\s*",       # 123 - title
        r"^\s*-\s*",          # - title
        r"\s+$",              # trailing space
        r"^\s+",              # leading space
    ]
    
    for v in videos:
        original = v.title
        new_title = original
        for p in patterns:
            new_title = re.sub(p, "", new_title, flags=re.IGNORECASE).strip()
        
        if new_title != original and new_title:
            v.title = new_title
            count += 1
            
    db.commit()
    res = {"updated": count}
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"Title normalization complete. Updated {count} videos.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    return res

def fix_broken_thumbnails(db: Session):
    """Find videos with missing thumbnails and re-trigger processing"""
    from app.services import VIPVideoProcessor
    videos = db.query(Video).filter(or_(Video.thumbnail_path.is_(None), Video.thumbnail_path == "")).all()
    count = 0
    
    p_ids = [v.id for v in videos]
    if p_ids:
        # Utilize the high-performance processor
        processor = VIPVideoProcessor()
        processor.process_batch(p_ids)
    
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"Thumbnail repair session finished for {len(p_ids)} videos.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    return {"retriggered": len(p_ids)}

def sync_video_durations(db: Session):
    """Update durations for videos that have 0 or null"""
    from app.services import VIPVideoProcessor
    videos = db.query(Video).filter(or_(Video.duration == 0, Video.duration.is_(None))).all()
    count = 0
    
    processor = VIPVideoProcessor()
    for v in videos:
        # Use ffprobe to get duration if possible
        try:
            meta = processor._ffprobe_fallback(v.url, {}, referer=v.source_url)
            if meta.get('duration'):
                v.duration = meta['duration']
                count += 1
        except:
            pass
            
    db.commit()
    return {"updated": count}

def scan_and_extract_file_sizes(db: Session):
    """Scan all videos and extract their file size if missing"""
    import requests
    videos = db.query(Video).all()
    updated_count = 0
    
    for v in videos:
        # Logic to check if we already have it
        stats = v.download_stats or {}
        if stats.get('size_mb'):
            continue
            
        size_mb = 0
        if v.storage_type == "local":
            # Extract from /static/ URL format
            path_part = v.url.replace('/static/', '', 1).lstrip('/')
            local_path = os.path.join("app", "static", path_part)
            if os.path.exists(local_path):
                size_mb = round(os.path.getsize(local_path) / (1024 * 1024), 2)
        elif v.url and v.url.startswith('http'):
            # Remote file - try HEAD request
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                if v.source_url:
                    headers['Referer'] = v.source_url
                
                # We use stream=True for requests.get if HEAD is blocked, but let's try HEAD first
                resp = requests.head(v.url, headers=headers, timeout=5, allow_redirects=True)
                if resp.status_code == 200:
                    content_length = int(resp.headers.get('Content-Length', 0))
                    if content_length > 0:
                        size_mb = round(content_length / (1024 * 1024), 2)
                elif resp.status_code == 405 or resp.status_code == 403:
                    # Retry with GET and closing immediately if HEAD failed
                    with requests.get(v.url, headers=headers, timeout=5, stream=True) as r:
                         content_length = int(r.headers.get('Content-Length', 0))
                         if content_length > 0:
                             size_mb = round(content_length / (1024 * 1024), 2)
            except:
                pass
                
        if size_mb > 0:
            stats['size_mb'] = size_mb
            v.download_stats = stats
            # Force SQLAlchemy to see the update for JSON column
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(v, "download_stats")
            updated_count += 1
            
    db.commit()
    res = {"updated_sizes": updated_count}
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"File size scan complete. Updated {updated_count} videos.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    return res

def refresh_poor_metadata(db: Session):
    """Find videos with zero duration, low resolution or missing thumbnails and re-extract data"""
    from app.services import VIPVideoProcessor
    from app.websockets import manager
    import json
    import asyncio
    import concurrent.futures
    
    # Identify videos with poor metadata
    # Criteria: duration <= 1 (usually 0 or placeholder), height <= 0 (missing resolution), or missing thumbnail
    videos = db.query(Video).filter(
        or_(
            Video.duration <= 1,
            Video.height <= 0,
            Video.thumbnail_path.is_(None),
            Video.thumbnail_path == ""
        )
    ).all()
    
    video_ids = [v.id for v in videos]
    count = len(video_ids)
    
    if video_ids:
        # Utilize the high-performance processor
        processor = VIPVideoProcessor()
        
        # We use force=True to ensure it re-extracts everything
        # Since process_batch doesn't take 'force', we use ThreadPoolExecutor directly or a modified loop
        max_workers = 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # We wrap it in a lambda to pass force=True
            futures = [executor.submit(processor.process_single_video, vid, force=True) for vid in video_ids]
            # Wait for completion (optional, but good for logging)
            concurrent.futures.wait(futures)
    
    from app.websockets import manager
    import json
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        msg = json.dumps({"type": "log", "message": f"Metadata refresh complete. Re-processed {count} videos.", "level": "success"})
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
    except: pass
    
    return {"refreshed": count}
