from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db, Video
from app.main import active_downloads

router = APIRouter(tags=["downloads"])

@router.get("/api/v1/downloads/active")
@router.get("/api/downloads/active")
def get_active_downloads():
    return active_downloads
