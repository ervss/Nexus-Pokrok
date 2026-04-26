"""
Link Health Monitoring Module
Validates stream URLs and refreshes broken links
"""
import requests
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import Video
import asyncio

async def check_link_health(url: str, timeout: int = 10) -> bool:
    """Check if a stream URL is accessible"""
    try:
        # Use HEAD request for efficiency
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code < 400
    except:
        # Fallback to GET with range header
        try:
            headers = {'Range': 'bytes=0-1024'}
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            return response.status_code in [200, 206]
        except:
            return False

def check_video_health(db: Session, video_id: int) -> dict:
    """Check health of a single video"""
    video = db.query(Video).get(video_id)
    if not video:
        return {'success': False, 'error': 'Video not found'}
    
    is_healthy = asyncio.run(check_link_health(video.url))
    
    video.last_checked = datetime.utcnow()
    video.check_count = (video.check_count or 0) + 1
    video.link_status = "working" if is_healthy else "broken"
    db.commit()
    
    return {
        'success': True,
        'video_id': video_id,
        'status': video.link_status,
        'url': video.url
    }

def check_all_videos_health(db: Session, max_age_hours: int = 24):
    """Check health of all videos that haven't been checked recently"""
    cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
    
    # Get videos that need checking
    videos = db.query(Video).filter(
        (Video.last_checked.is_(None)) | (Video.last_checked < cutoff_time),
        Video.status == "ready_to_stream"
    ).all()
    
    results = {
        'total': len(videos),
        'working': 0,
        'broken': 0,
        'checked': 0
    }
    
    for video in videos:
        is_healthy = asyncio.run(check_link_health(video.url))
        video.last_checked = datetime.utcnow()
        video.check_count = (video.check_count or 0) + 1
        video.link_status = "working" if is_healthy else "broken"
        
        if is_healthy:
            results['working'] += 1
        else:
            results['broken'] += 1
        results['checked'] += 1
        
        # Commit every 10 videos to avoid long transactions
        if results['checked'] % 10 == 0:
            db.commit()
    
    db.commit()
    logging.info(f"Health check complete: {results}")
    return results

def get_library_health_stats(db: Session) -> dict:
    """Get overall library health statistics"""
    total = db.query(Video).filter(Video.status == "ready_to_stream").count()
    working = db.query(Video).filter(Video.link_status == "working").count()
    broken = db.query(Video).filter(Video.link_status == "broken").count()
    unknown = db.query(Video).filter(Video.link_status == "unknown").count()
    
    never_checked = db.query(Video).filter(
        Video.last_checked.is_(None),
        Video.status == "ready_to_stream"
    ).count()
    
    return {
        'total': total,
        'working': working,
        'broken': broken,
        'unknown': unknown,
        'never_checked': never_checked,
        'health_percentage': round((working / total * 100) if total > 0 else 0, 1)
    }

def refresh_broken_links(db: Session):
    """Attempt to refresh all broken links by re-extracting from source_url"""
    from app.services import VIPVideoProcessor
    
    broken_videos = db.query(Video).filter(
        Video.link_status == "broken",
        Video.source_url.isnot(None)
    ).all()
    
    processor = VIPVideoProcessor()
    refreshed = 0
    
    for video in broken_videos:
        try:
            # Re-process the video to get fresh stream URL
            processor.process_single_video(video.id, force=True)
            refreshed += 1
        except Exception as e:
            logging.error(f"Failed to refresh video {video.id}: {e}")
    
    return {
        'total_broken': len(broken_videos),
        'refreshed': refreshed
    }
