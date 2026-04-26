"""Video link health checks (library-wide, not process /health)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.health_monitor import (
    check_all_videos_health,
    check_video_health,
    get_library_health_stats,
    refresh_broken_links,
)

router = APIRouter(tags=["library-health"])


@router.get("/health/stats")
def health_stats(db: Session = Depends(get_db)):
    return get_library_health_stats(db)


@router.post("/health/check/{video_id}")
def check_single_video(video_id: int, db: Session = Depends(get_db)):
    return check_video_health(db, video_id)


@router.post("/health/check-all")
async def check_all_health(background_tasks: BackgroundTasks, max_age_hours: int = 24):
    def check_task():
        db = SessionLocal()
        try:
            check_all_videos_health(db, max_age_hours)
        finally:
            db.close()

    background_tasks.add_task(check_task)
    return {"status": "checking", "message": "Health check started in background"}


@router.post("/health/refresh-broken")
async def refresh_broken(background_tasks: BackgroundTasks):
    def refresh_task():
        db = SessionLocal()
        try:
            result = refresh_broken_links(db)
            logging.info(f"Refreshed {result['refreshed']} out of {result['total_broken']} broken links")
        finally:
            db.close()

    background_tasks.add_task(refresh_task)
    return {"status": "refreshing", "message": "Link refresh started in background"}
