#!/usr/bin/env python3
"""
Database backup restoration script.

Restores database from compressed backup files with verification.
"""
import os
import sys
import gzip
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
import logging

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseRestore:
    """Handles database restoration from backups."""
    
    def __init__(self, db_path: str = None, backup_dir: str = None):
        """
        Initialize restore manager.
        
        Args:
            db_path: Path to database file (default from config)
            backup_dir: Backup directory (default from config)
        """
        if db_path is None:
            db_url = config.DATABASE_URL
            if db_url.startswith('sqlite:///'):
                db_path = db_url.replace('sqlite:///', '')
            else:
                raise ValueError("Only SQLite databases supported for restore")
        
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir or config.BACKUP_DIR)
    
    def list_backups(self) -> list:
        """
        List available backups.
        
        Returns:
            List of backup file paths
        """
        backups = sorted(self.backup_dir.glob("videos_backup_*.db.gz"), reverse=True)
        return backups
    
    def restore_from_backup(self, backup_path: str, verify: bool = True):
        """
        Restore database from a backup file.
        
        Args:
            backup_path: Path to backup file
            verify: Verify integrity after restore
        """
        backup_path = Path(backup_path)
        
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        logger.info(f"Restoring from backup: {backup_path.name}")
        
        # Create safety backup of current database
        if self.db_path.exists():
            safety_backup = self.db_path.with_suffix('.db.pre-restore')
            logger.info(f"Creating safety backup: {safety_backup}")
            shutil.copy2(self.db_path, safety_backup)
        
        try:
            # Decompress and restore
            with gzip.open(backup_path, 'rb') as f_in:
                with open(self.db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            logger.info("Database file restored")
            
            # Verify integrity
            if verify:
                self._verify_database()
                logger.info("✓ Database restore successful and verified")
            
            # Remove safety backup if successful
            safety_backup = self.db_path.with_suffix('.db.pre-restore')
            if safety_backup.exists():
                logger.info("Removing safety backup")
                safety_backup.unlink()
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            # Attempt to restore from safety backup
            safety_backup = self.db_path.with_suffix('.db.pre-restore')
            if safety_backup.exists():
                logger.info("Restoring from safety backup...")
                shutil.copy2(safety_backup, self.db_path)
                logger.info("Original database restored")
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
            
            # Check tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            expected_tables = {'videos', 'smart_playlists', 'search_history', 'alembic_version'}
            if not expected_tables.issubset(set(tables)):
                missing = expected_tables - set(tables)
                logger.warning(f"Expected tables missing: {missing}")
            
            logger.info("Database integrity check passed")
            
        finally:
            conn.close()


def main():
    """Main restore entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database restore utility")
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help="List available backups"
    )
    parser.add_argument(
        '--restore', '-r',
        metavar='BACKUP',
        help="Restore from specified backup file"
    )
    parser.add_argument(
        '--latest',
        action='store_true',
        help="Restore from latest backup"
    )
    parser.add_argument(
        '--no-verify',
        action='store_true',
        help="Skip integrity verification after restore"
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
        restore_manager = DatabaseRestore(
            db_path=args.db_path,
            backup_dir=args.backup_dir
        )
        
        if args.list:
            backups = restore_manager.list_backups()
            if not backups:
                print("No backups found")
                return 1
            
            print(f"\nAvailable backups in {restore_manager.backup_dir}:")
            print("-" * 70)
            print(f"{'#':<4} {'Filename':<40} {'Size (MB)':>12} {'Created':>18}")
            print("-" * 70)
            
            for i, backup in enumerate(backups, 1):
                size_mb = backup.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(backup.stat().st_mtime)
                print(f"{i:<4} {backup.name:<40} {size_mb:>12.2f} {mtime.strftime('%Y-%m-%d %H:%M:%S'):>18}")
            
            print("-" * 70)
            print(f"Total backups: {len(backups)}")
            print("\nTo restore, use: python scripts/db_restore.py --restore <filename>")
            print("Or restore latest: python scripts/db_restore.py --latest")
            
        elif args.latest:
            backups = restore_manager.list_backups()
            if not backups:
                print("No backups found")
                return 1
            
            latest_backup = backups[0]
            print(f"Restoring from latest backup: {latest_backup.name}")
            
            # Confirm with user
            response = input("This will overwrite the current database. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Restore cancelled")
                return 0
            
            restore_manager.restore_from_backup(latest_backup, verify=not args.no_verify)
            print(f"✓ Database restored from {latest_backup.name}")
            
        elif args.restore:
            backup_path = Path(args.restore)
            if not backup_path.is_absolute():
                backup_path = restore_manager.backup_dir / backup_path
            
            if not backup_path.exists():
                print(f"Error: Backup file not found: {backup_path}")
                return 1
            
            print(f"Restoring from backup: {backup_path.name}")
            
            # Confirm with user
            response = input("This will overwrite the current database. Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Restore cancelled")
                return 0
            
            restore_manager.restore_from_backup(backup_path, verify=not args.no_verify)
            print(f"✓ Database restored from {backup_path.name}")
            
        else:
            parser.print_help()
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Restore operation failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
