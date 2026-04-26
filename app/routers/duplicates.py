"""Duplicate detection API."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.duplicate_detector import compute_all_phashes, find_duplicates, mark_as_duplicate

router = APIRouter(tags=["duplicates"])


class MarkDuplicateBody(BaseModel):
    duplicate_id: int
    original_id: int


@router.post("/duplicates/scan")
async def scan_duplicates(background_tasks: BackgroundTasks):
    def scan_task():
        db_local = SessionLocal()
        try:
            compute_all_phashes(db_local)
            duplicates = find_duplicates(db_local, threshold=5)
            logging.info(f"Found {len(duplicates)} potential duplicates")
        finally:
            db_local.close()

    background_tasks.add_task(scan_task)
    return {"status": "scanning", "message": "Duplicate scan started in background"}


@router.get("/duplicates")
def get_duplicates(db: Session = Depends(get_db)):
    duplicates = find_duplicates(db, threshold=5)
    return {"duplicates": duplicates, "count": len(duplicates)}


@router.post("/duplicates/mark")
def mark_duplicate(body: MarkDuplicateBody, db: Session = Depends(get_db)):
    success = mark_as_duplicate(db, body.duplicate_id, body.original_id)
    return {"success": success}
