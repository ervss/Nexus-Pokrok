#!/usr/bin/env python3
"""
Clean Database - Remove videos with null/empty titles
This script fixes the root cause of the JavaScript errors
"""

import sqlite3
import sys
from pathlib import Path

def clean_database():
    """Remove all videos with null or empty titles"""
    
    # Find database
    db_path = Path(__file__).parent / "videos.db"
    
    if not db_path.exists():
        print(f"❌ Database not found at: {db_path}")
        return False
    
    print("🔍 Connecting to database...")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Count problematic videos
        cursor.execute("SELECT COUNT(*) FROM videos WHERE title IS NULL OR title = '' OR TRIM(title) = ''")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("✅ No videos with null/empty titles found!")
            return True
        
        print(f"⚠️  Found {count} videos with null/empty titles")
        
        # Show some examples
        cursor.execute("SELECT id, source_url, created_at FROM videos WHERE title IS NULL OR title = '' OR TRIM(title) = '' LIMIT 5")
        examples = cursor.fetchall()
        
        print("\nExamples:")
        for video_id, url, created in examples:
            print(f"  - ID: {video_id}, URL: {url[:50]}..., Created: {created}")
        
        # Ask for confirmation
        response = input(f"\n❓ Delete these {count} videos? (yes/no): ").strip().lower()
        
        if response not in ['yes', 'y']:
            print("❌ Cancelled. No videos deleted.")
            return False
        
        # Delete them
        cursor.execute("DELETE FROM videos WHERE title IS NULL OR title = '' OR TRIM(title) = ''")
        conn.commit()
        
        print(f"✅ Successfully deleted {count} videos with null/empty titles!")
        
        # Show new count
        cursor.execute("SELECT COUNT(*) FROM videos")
        total = cursor.fetchone()[0]
        print(f"📊 Total videos remaining: {total}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("  Video Database Cleaner - Fix Null Title Errors")
    print("=" * 60)
    print()
    
    success = clean_database()
    
    print()
    if success:
        print("✅ Database cleanup complete!")
        print("\nNext steps:")
        print("1. Restart your server")
        print("2. Refresh your browser (Ctrl+Shift+R)")
        print("3. Errors should be gone!")
    else:
        print("❌ Cleanup failed or was cancelled")
    
    print()
    input("Press Enter to exit...")
