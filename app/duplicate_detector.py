"""
Duplicate Detection Module
Uses perceptual hashing to find visually similar thumbnails
"""
import imagehash
from PIL import Image
import os
import logging
from sqlalchemy.orm import Session
from app.database import Video

def compute_phash(image_path: str) -> str:
    """Compute perceptual hash of an image"""
    try:
        if not os.path.exists(image_path):
            return None
        img = Image.open(image_path)
        hash_val = imagehash.phash(img)
        return str(hash_val)
    except Exception as e:
        logging.error(f"Failed to compute phash for {image_path}: {e}")
        return None

def hamming_distance(hash1: str, hash2: str) -> int:
    """Calculate hamming distance between two hashes"""
    if not hash1 or not hash2:
        return 999
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return h1 - h2
    except:
        return 999

def find_duplicates(db: Session, threshold: int = 5):
    """
    Find duplicate videos based on perceptual hash similarity
    threshold: Maximum hamming distance to consider as duplicate (0-64, lower = more strict)
    """
    duplicates = []
    
    # Get all videos with phash
    videos = db.query(Video).filter(Video.phash.isnot(None), Video.duplicate_of.is_(None)).all()
    
    for i, video in enumerate(videos):
        for other_video in videos[i+1:]:
            distance = hamming_distance(video.phash, other_video.phash)
            if distance <= threshold:
                # Consider the older video as original
                original = video if video.id < other_video.id else other_video
                duplicate = other_video if video.id < other_video.id else video
                
                duplicates.append({
                    'original_id': original.id,
                    'original_title': original.title,
                    'duplicate_id': duplicate.id,
                    'duplicate_title': duplicate.title,
                    'similarity': 100 - (distance / 64 * 100),
                    'distance': distance
                })
    
    return duplicates

def mark_as_duplicate(db: Session, duplicate_id: int, original_id: int):
    """Mark a video as duplicate of another"""
    duplicate = db.query(Video).get(duplicate_id)
    if duplicate:
        duplicate.duplicate_of = original_id
        db.commit()
        return True
    return False

def compute_all_phashes(db: Session):
    """Compute phashes for all videos that don't have one"""
    videos = db.query(Video).filter(Video.phash.is_(None), Video.thumbnail_path.isnot(None)).all()
    count = 0
    
    for video in videos:
        thumb_path = f"app{video.thumbnail_path.split('?')[0]}"  # Remove query params
        phash = compute_phash(thumb_path)
        if phash:
            video.phash = phash
            count += 1
    
    db.commit()
    logging.info(f"Computed phashes for {count} videos")
    return count
