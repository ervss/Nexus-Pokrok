import asyncio
from app.workers.celery_app import celery_app
from app.database import SessionLocal, Video
from app.services import VIPVideoProcessor

@celery_app.task(bind=True, name="process_video_task")
def process_video_task(self, video_id: int, force: bool = False, quality_mode: str = "mp4", extractor: str = "auto"):
    processor = VIPVideoProcessor()
    try:
        processor.process_single_video(video_id, force=force, quality_mode=quality_mode, extractor=extractor)
        return {"status": "success", "video_id": video_id}
    except Exception as e:
        self.update_state(state="FAILURE", meta={"exc": str(e)})
        raise e

@celery_app.task(bind=True, name="refresh_video_link_task")
def refresh_video_link_task(self, video_id: int):
    from app.main import refresh_video_link
    try:
        refresh_video_link(video_id)
        return {"status": "success", "video_id": video_id}
    except Exception as e:
        self.update_state(state="FAILURE", meta={"exc": str(e)})
        raise e
