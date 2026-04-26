import sqlite3
import os

db_path = 'videos.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, source_url, title FROM videos WHERE url LIKE '%vidara%' OR source_url LIKE '%vidara%' LIMIT 10")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    conn.close()
else:
    print("Database not found")
