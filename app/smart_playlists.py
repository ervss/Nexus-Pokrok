"""
Smart Playlist Module
Dynamic playlists with rule-based filtering
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.database import Video, SmartPlaylist
from datetime import datetime, timedelta
import logging

def evaluate_rule(video: Video, rule: dict) -> bool:
    """Evaluate if a video matches a single rule"""
    field = rule.get('field')
    operator = rule.get('operator')
    value = rule.get('value')
    
    if not field or not operator:
        return True
    
    # Get the actual value from video
    video_value = getattr(video, field, None)
    
    if operator == 'equals':
        return str(video_value).lower() == str(value).lower()
    elif operator == 'not_equals':
        return str(video_value).lower() != str(value).lower()
    elif operator == 'contains':
        return value.lower() in str(video_value).lower()
    elif operator == 'not_contains':
        return value.lower() not in str(video_value).lower()
    elif operator == 'greater_than':
        try:
            return float(video_value) > float(value)
        except:
            return False
    elif operator == 'less_than':
        try:
            return float(video_value) < float(value)
        except:
            return False
    elif operator == 'in_last_days':
        try:
            days = int(value)
            cutoff = datetime.utcnow() - timedelta(days=days)
            return video.created_at > cutoff
        except:
            return False
    elif operator == 'is_true':
        return bool(video_value)
    elif operator == 'is_false':
        return not bool(video_value)
    
    return True

def get_smart_playlist_videos(db: Session, playlist_id: int) -> list:
    """Get all videos matching a smart playlist's rules"""
    playlist = db.query(SmartPlaylist).get(playlist_id)
    if not playlist:
        return []
    
    rules = playlist.rules
    match_type = rules.get('match', 'all')  # 'all' or 'any'
    rule_list = rules.get('rules', [])
    
    # Start with all ready videos
    all_videos = db.query(Video).filter(Video.status == "ready_to_stream").all()
    
    matching_videos = []
    for video in all_videos:
        if match_type == 'all':
            # All rules must match
            if all(evaluate_rule(video, rule) for rule in rule_list):
                matching_videos.append(video)
        else:
            # Any rule must match
            if any(evaluate_rule(video, rule) for rule in rule_list):
                matching_videos.append(video)
    
    return matching_videos

def create_smart_playlist(db: Session, name: str, rules: dict) -> SmartPlaylist:
    """Create a new smart playlist"""
    # Check if name already exists
    existing = db.query(SmartPlaylist).filter(SmartPlaylist.name == name).first()
    if existing:
        raise ValueError(f"Playlist '{name}' already exists")
    
    playlist = SmartPlaylist(name=name, rules=rules)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    
    logging.info(f"Created smart playlist: {name}")
    return playlist

def update_smart_playlist(db: Session, playlist_id: int, name: str = None, rules: dict = None):
    """Update an existing smart playlist"""
    playlist = db.query(SmartPlaylist).get(playlist_id)
    if not playlist:
        raise ValueError("Playlist not found")
    
    if name:
        playlist.name = name
    if rules:
        playlist.rules = rules
    
    db.commit()
    return playlist

def delete_smart_playlist(db: Session, playlist_id: int):
    """Delete a smart playlist"""
    playlist = db.query(SmartPlaylist).get(playlist_id)
    if playlist:
        db.delete(playlist)
        db.commit()
        return True
    return False

def get_all_smart_playlists(db: Session):
    """Get all smart playlists with video counts"""
    playlists = db.query(SmartPlaylist).all()
    result = []
    
    for playlist in playlists:
        videos = get_smart_playlist_videos(db, playlist.id)
        result.append({
            'id': playlist.id,
            'name': playlist.name,
            'rules': playlist.rules,
            'video_count': len(videos),
            'created_at': playlist.created_at.isoformat() if playlist.created_at else None
        })
    
    return result

# Preset smart playlists
PRESET_PLAYLISTS = [
    {
        'name': 'Recently Added (7 Days)',
        'rules': {
            'match': 'all',
            'rules': [
                {'field': 'created_at', 'operator': 'in_last_days', 'value': '7'}
            ]
        }
    },
    {
        'name': 'HD & Above (1080p+)',
        'rules': {
            'match': 'all',
            'rules': [
                {'field': 'height', 'operator': 'greater_than', 'value': '1079'}
            ]
        }
    },
    {
        'name': 'Unwatched',
        'rules': {
            'match': 'all',
            'rules': [
                {'field': 'is_watched', 'operator': 'is_false', 'value': ''}
            ]
        }
    },
    {
        'name': 'Long Videos (20+ min)',
        'rules': {
            'match': 'all',
            'rules': [
                {'field': 'duration', 'operator': 'greater_than', 'value': '1200'}
            ]
        }
    }
]

def create_preset_playlists(db: Session):
    """Create preset smart playlists if they don't exist"""
    for preset in PRESET_PLAYLISTS:
        existing = db.query(SmartPlaylist).filter(SmartPlaylist.name == preset['name']).first()
        if not existing:
            try:
                create_smart_playlist(db, preset['name'], preset['rules'])
            except:
                pass
