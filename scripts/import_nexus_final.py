import sqlite3
import os
import shutil
import logging
from datetime import datetime

# Configuration
SOURCE_DIR = r"c:\Users\Peto\Downloads\Compressed\Nexus-Dream-main\Nexus-Dream_Stable"
TARGET_DIR = os.getcwd()

SOURCE_DB = os.path.join(SOURCE_DIR, "videos.db")
TARGET_DB = os.path.join(TARGET_DIR, "videos.db")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def migrate_table(table_name, unique_col=None):
    logging.info(f"--- Migrating table: {table_name} ---")
    
    if not os.path.exists(SOURCE_DB):
        logging.error("Source database not found")
        return

    src_conn = sqlite3.connect(SOURCE_DB)
    src_conn.row_factory = sqlite3.Row
    src_cursor = src_conn.cursor()
    
    tgt_conn = sqlite3.connect(TARGET_DB)
    tgt_cursor = tgt_conn.cursor()
    
    try:
        # Check if table exists in source
        src_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not src_cursor.fetchone():
            logging.warning(f"Table {table_name} does not exist in source")
            return

        # Check if table exists in target
        tgt_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        if not tgt_cursor.fetchone():
            logging.warning(f"Table {table_name} does not exist in target")
            return

        # Get columns
        src_cursor.execute(f"SELECT * FROM {table_name} LIMIT 1")
        row = src_cursor.fetchone()
        if not row:
            logging.info(f"Table {table_name} is empty in source")
            return
            
        columns = list(row.keys())
        if 'id' in columns:
            columns.remove('id')
            
        # Get target columns to ensure compatibility
        tgt_cursor.execute(f"PRAGMA table_info({table_name})")
        tgt_cols = [c[1] for c in tgt_cursor.fetchall()]
        
        valid_columns = [c for c in columns if c in tgt_cols]
        col_str = ", ".join(valid_columns)
        
        # Select all from source
        src_cursor.execute(f"SELECT {col_str} FROM {table_name}")
        rows = src_cursor.fetchall()
        
        count = 0
        skipped = 0
        
        for r in rows:
            # Check for duplicate if unique_col is provided
            if unique_col and unique_col in valid_columns:
                val = r[unique_col]
                tgt_cursor.execute(f"SELECT 1 FROM {table_name} WHERE {unique_col} = ?", (val,))
                if tgt_cursor.fetchone():
                    skipped += 1
                    continue
            
            # Insert
            placeholders = ", ".join(["?"] * len(valid_columns))
            values = tuple(r[c] for c in valid_columns)
            
            insert_sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})"
            tgt_cursor.execute(insert_sql, values)
            count += 1
            
        tgt_conn.commit()
        logging.info(f"Migrated {count} records to {table_name}, skipped {skipped} duplicates.")
        
    except Exception as e:
        logging.error(f"Failed to migrate table {table_name}: {e}")
    finally:
        src_conn.close()
        tgt_conn.close()

def copy_folder_contents(subpath):
    src = os.path.join(SOURCE_DIR, subpath)
    dst = os.path.join(TARGET_DIR, subpath)
    
    if not os.path.exists(src):
        logging.warning(f"Source folder not found: {src}")
        return
        
    if not os.path.exists(dst):
        os.makedirs(dst)
        
    logging.info(f"--- Copying contents of {subpath} ---")
    files = os.listdir(src)
    count = 0
    skipped = 0
    for f in files:
        src_file = os.path.join(src, f)
        dst_file = os.path.join(dst, f)
        if os.path.isfile(src_file):
            if not os.path.exists(dst_file):
                shutil.copy2(src_file, dst_file)
                count += 1
            else:
                skipped += 1
    
    logging.info(f"Copied {count} files, skipped {skipped} existing files in {subpath}")

def copy_batch_files():
    logging.info("--- Copying batch link files ---")
    files = [f for f in os.listdir(SOURCE_DIR) if f.startswith("ws_links") and f.endswith(".txt")]
    count = 0
    for f in files:
        src = os.path.join(SOURCE_DIR, f)
        dst = os.path.join(TARGET_DIR, f)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            count += 1
    logging.info(f"Copied {count} batch files.")

if __name__ == "__main__":
    # Ensure target DB is initialized
    # We assume the user has run the app at least once or we can call init_db if we want to be safe,
    # but since this is a migration script we'll just go ahead.
    
    migrate_table("videos", unique_col="url")
    migrate_table("smart_playlists", unique_col="name")
    migrate_table("search_history") # No obvious unique col for history, maybe skip duplicates later
    
    copy_batch_files()
    copy_folder_contents(r"app\static\thumbnails")
    copy_folder_contents(r"app\static\previews")
    copy_folder_contents(r"app\static\subtitles")
    
    logging.info("Done!")
