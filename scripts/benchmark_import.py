import os
import time
import datetime
import asyncio
from unittest.mock import MagicMock, patch

# Set environment variables for config
os.environ['DASHBOARD_PASSWORD'] = 'P@ssword12345'
os.environ['SECRET_KEY'] = 'secret_key_for_testing_purposes_only'
os.environ['DATABASE_URL'] = 'sqlite:///./benchmark.db'

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video, DiscoveredVideo
from app.main import import_selected_videos

# Setup database
engine = create_engine(os.environ['DATABASE_URL'])
SessionLocal = sessionmaker(bind=engine)

def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Create some existing videos (20%)
    for i in range(20):
        video = Video(
            title=f"Existing Video {i}",
            url=f"http://example.com/video_{i}",
            status='ready'
        )
        db.add(video)

    # Create discovered videos (100)
    video_ids = []
    for i in range(100):
        discovered = DiscoveredVideo(
            profile_id=1,
            profile_name="Test Profile",
            title=f"Discovered Video {i}",
            url=f"http://example.com/video_{i}",
            source_url=f"http://example.com/source_{i}",
            thumbnail=f"http://example.com/thumb_{i}.jpg",
            duration=120.0,
            width=1920,
            height=1080,
            source="Test"
        )
        db.add(discovered)
        db.flush()
        video_ids.append(discovered.id)

    db.commit()
    db.close()
    return video_ids

async def run_benchmark(video_ids):
    db = SessionLocal()
    try:
        start_time = time.time()
        # Mock process_video_task.delay
        with patch('app.workers.tasks.process_video_task.delay') as mock_delay:
            await import_selected_videos(video_ids=video_ids, db=db)
        end_time = time.time()
        return end_time - start_time
    finally:
        db.close()

if __name__ == "__main__":
    v_ids = setup_db()

    # Warm up
    # (Not really needed for I/O bound N+1 but good practice)

    duration = asyncio.run(run_benchmark(v_ids))
    print(f"Benchmark duration: {duration:.4f} seconds")

    # Cleanup
    if os.path.exists('benchmark.db'):
        os.remove('benchmark.db')
