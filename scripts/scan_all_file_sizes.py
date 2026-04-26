#!/usr/bin/env python3
"""
One-time script to scan and populate file sizes for all existing videos.
Run this after the update to populate download_stats.size_mb for existing videos.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.maintenance import scan_and_extract_file_sizes

def main():
    print("=" * 60)
    print("FILE SIZE SCANNER")
    print("=" * 60)
    print("This script will scan all videos and extract file sizes.")
    print("This may take a while depending on the number of videos.")
    print()
    
    db = SessionLocal()
    try:
        result = scan_and_extract_file_sizes(db)
        print()
        print("=" * 60)
        print(f"✓ SCAN COMPLETE")
        print(f"  Updated: {result['updated_sizes']} videos")
        print("=" * 60)
    except Exception as e:
        print(f"✗ ERROR: {e}")
        return 1
    finally:
        db.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
