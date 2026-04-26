#!/usr/bin/env python3
"""
Automated database backup script with rotation.

Features:
- Creates timestamped compressed database backups
- Implements retention policy (7 days, 4 weeks, 3 months)
- Smart rotation to prevent disk overflow
- Integrity verification
"""
import os
import sys
import gzip
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseBackup:
    """Handles database backup and rotation."""
    
    def __init__(self, db_path: str = None, backup_dir: str = None):
        """
        Initialize backup manager.
        
        Args:
            db_path: Path to database file (default from config)
            backup_dir: Backup directory (default from config)
        """
        # Extract DB path from URL
        if db_path is None:
            db_url = config.DATABASE_URL
            if db_url.startswith('sqlite:///'):
                db_path = db_url.replace('sqlite:///', '')
            else:
                raise ValueError("Only SQLite databases supported for backup")
        
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir or config.BACKUP_DIR)
        self.backup_dir.mkdir(exist_ok=True, parents=True)
        
        # Retention policy
        self.retention_days = config.BACKUP_RETENTION_DAYS
        self.retention_weeks = 4  # Keep 4 weekly backups
        self.retention_months = 3  # Keep 3 monthly backups
    
    def create_backup(self) -> Path:
        """
        Create a compressed backup of the database.
        
        Returns:
            Path to created backup file
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"videos_backup_{timestamp}.db.gz"
        backup_path = self.backup_dir / backup_name
        
        logger.info(f"Creating backup: {backup_name}")
        
        try:
            # Verify database integrity before backup
            self._verify_database()
            
            # Create compressed backup
            with open(self.db_path, 'rb') as f_in:
                with gzip.open(backup_path, 'wb', compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Verify backup file was created
            if not backup_path.exists():
                raise RuntimeError("Backup file was not created")
            
            backup_size_mb = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"Backup created successfully: {backup_size_mb:.2f} MB")
            
            return backup_path
            
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            if backup_path.exists():
                backup_path.unlink()  # Clean up partial backup
            raise
    
    def _verify_database(self):
        """Verify database integrity."""
        logger.info("Verifying database integrity...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"Database integrity check failed: {result}")
            logger.info("Database integrity check passed")
        finally:
            conn.close()
    
    def rotate_backups(self):
        """
        Implement retention policy to remove old backups.
        
        Policy:
        - Daily: Keep last N days (config.BACKUP_RETENTION_DAYS)
        - Weekly: Keep 4 weekly backups (first backup of each week)
        - Monthly: Keep 3 monthly backups (first backup of each month)
        """
        logger.info("Rotating old backups...")
        
        backups = sorted(self.backup_dir.glob("videos_backup_*.db.gz"))
        if not backups:
            logger.info("No backups to rotate")
            return
        
        now = datetime.now()
        keep = set()
        
        # Parse backup timestamps
        backup_dates = []
        for backup in backups:
            try:
                # Extract timestamp from filename
                name = backup.stem.replace('.db', '')
                timestamp_str = name.split('_')[-2] + '_' + name.split('_')[-1]
                backup_date = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                backup_dates.append((backup, backup_date))
            except Exception as e:
                logger.warning(f"Could not parse backup date for {backup.name}: {e}")
                keep.add(backup)  # Keep if we can't parse date
        
        # Sort by date
        backup_dates.sort(key=lambda x: x[1], reverse=True)
        
        # Daily retention
        daily_cutoff = now - timedelta(days=self.retention_days)
        for backup, backup_date in backup_dates:
            if backup_date >= daily_cutoff:
                keep.add(backup)
        
        # Weekly retention (first backup of each week)
        weekly_cutoff = now - timedelta(weeks=self.retention_weeks)
        weekly_backups = {}
        for backup, backup_date in backup_dates:
            if backup_date >= weekly_cutoff:
                week_key = backup_date.strftime('%Y-%W')
                if week_key not in weekly_backups:
                    weekly_backups[week_key] = backup
        keep.update(weekly_backups.values())
        
        # Monthly retention (first backup of each month)
        monthly_cutoff = now - timedelta(days=30 * self.retention_months)
        monthly_backups = {}
        for backup, backup_date in backup_dates:
            if backup_date >= monthly_cutoff:
                month_key = backup_date.strftime('%Y-%m')
                if month_key not in monthly_backups:
                    monthly_backups[month_key] = backup
        keep.update(monthly_backups.values())
        
        # Delete backups not in keep set
        deleted_count = 0
        for backup in backups:
            if backup not in keep:
                logger.info(f"Deleting old backup: {backup.name}")
                backup.unlink()
                deleted_count += 1
        
        logger.info(f"Rotation complete. Deleted {deleted_count} old backups, kept {len(keep)}")
    
    def list_backups(self):
        """List all available backups with details."""
        backups = sorted(self.backup_dir.glob("videos_backup_*.db.gz"), reverse=True)
        
        if not backups:
            print("No backups found")
            return
        
        print(f"\nAvailable backups in {self.backup_dir}:")
        print("-" * 70)
        print(f"{'Filename':<40} {'Size (MB)':>12} {'Created':>18}")
        print("-" * 70)
        
        for backup in backups:
            size_mb = backup.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(backup.stat().st_mtime)
            print(f"{backup.name:<40} {size_mb:>12.2f} {mtime.strftime('%Y-%m-%d %H:%M:%S'):>18}")
        
        print("-" * 70)
        print(f"Total backups: {len(backups)}")


def main():
    """Main backup entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database backup utility")
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help="List available backups"
    )
    parser.add_argument(
        '--rotate-only', '-r',
        action='store_true',
        help="Only rotate old backups, don't create new one"
    )
    parser.add_argument(
        '--db-path',
        help="Path to database file (default from config)"
    )
    parser.add_argument(
        '--backup-dir',
        help="Backup directory (default from config)"
    )
    
    args = parser.parse_args()
    
    try:
        backup_manager = DatabaseBackup(
            db_path=args.db_path,
            backup_dir=args.backup_dir
        )
        
        if args.list:
            backup_manager.list_backups()
        elif args.rotate_only:
            backup_manager.rotate_backups()
        else:
            # Create backup and rotate
            backup_path = backup_manager.create_backup()
            print(f"✓ Backup created: {backup_path}")
            backup_manager.rotate_backups()
            backup_manager.list_backups()
        
        return 0
        
    except Exception as e:
        logger.error(f"Backup operation failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
