"""Library maintenance / repair API."""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Body, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import SessionLocal, Video, get_db
from app.duplicate_detector import compute_all_phashes
from app.maintenance import (
    auto_resolve_duplicates,
    cleanup_broken_links,
    fix_broken_thumbnails,
    get_duplicates_by_hash,
    get_duplicates_by_name,
    normalize_all_titles,
    scan_and_extract_file_sizes,
    sync_video_durations,
    refresh_poor_metadata,
)
from app.services import VIPVideoProcessor

router = APIRouter(tags=["maintenance"])


@router.get("/maintenance/duplicates/name")
def list_name_duplicates(db: Session = Depends(get_db)):
    return get_duplicates_by_name(db)


@router.get("/maintenance/duplicates/hash")
def list_hash_duplicates(db: Session = Depends(get_db), threshold: int = 5):
    return get_duplicates_by_hash(db, threshold)


@router.post("/maintenance/duplicates/resolve")
def resolve_dups(background_tasks: BackgroundTasks, type: str = Body(..., embed=True)):
    def run_resolve():
        db = SessionLocal()
        try:
            auto_resolve_duplicates(db, type)
        finally:
            db.close()

    background_tasks.add_task(run_resolve)
    return {"status": "started", "message": f"Auto-resolving {type} duplicates in background"}


@router.post("/maintenance/cleanup")
def cleanup_db(background_tasks: BackgroundTasks, delete_permanently: bool = Body(False, embed=True)):
    def run_cleanup():
        db = SessionLocal()
        try:
            cleanup_broken_links(db, delete_permanently)
        finally:
            db.close()

    background_tasks.add_task(run_cleanup)
    return {"status": "started", "message": "Database cleanup started in background"}


@router.post("/maintenance/normalize-titles")
def normalize_titles_route(background_tasks: BackgroundTasks):
    def run_normalize():
        db = SessionLocal()
        try:
            normalize_all_titles(db)
        finally:
            db.close()

    background_tasks.add_task(run_normalize)
    return {"status": "started", "message": "Title normalization started in background"}


@router.post("/maintenance/fix-thumbnails")
def fix_thumbnails_route(background_tasks: BackgroundTasks):
    def run_fix():
        db = SessionLocal()
        try:
            fix_broken_thumbnails(db)
        finally:
            db.close()

    background_tasks.add_task(run_fix)
    return {"status": "started", "message": "Thumbnail repair started in background"}


@router.post("/maintenance/sync-durations")
def sync_durations_route(background_tasks: BackgroundTasks):
    def run_sync():
        db = SessionLocal()
        try:
            sync_video_durations(db)
        finally:
            db.close()

    background_tasks.add_task(run_sync)
    return {"status": "started", "message": "Duration sync started in background"}


@router.post("/maintenance/scan-sizes")
def scan_sizes_route(background_tasks: BackgroundTasks):
    def run_scan():
        db = SessionLocal()
        try:
            scan_and_extract_file_sizes(db)
        finally:
            db.close()

    background_tasks.add_task(run_scan)
    return {"status": "started", "message": "File size scan started in background"}


@router.post("/maintenance/repair-import-streams")
def repair_import_streams_route(
    background_tasks: BackgroundTasks,
    limit: int = Body(250, embed=True),
):
    safe_limit = max(1, min(int(limit or 250), 1000))

    def _needs_repair(v: Video) -> bool:
        u = (v.url or "").strip().lower()
        su = (v.source_url or "").strip().lower()

        if not u:
            return False

        if ("http://" in u or "https://" in u) and not u.startswith(("http://", "https://", "file://", "/")):
            return True
        if "function/" in u and ("http://" in u or "https://" in u):
            return True

        if "camwhores.tv/videos/" in u:
            return True
        if "pixeldrain.com/u/" in u or "pixeldrain.com/l/" in u:
            return True

        if ("camwhores.tv/videos/" in su or "pixeldrain.com/u/" in su) and (v.duration or 0) == 0 and (v.height or 0) == 0:
            return True

        return False

    def run_repair():
        db_local = SessionLocal()
        repaired = 0
        failed = 0
        scanned = 0
        queued = 0
        try:
            processor = VIPVideoProcessor()
            candidates = (
                db_local.query(Video)
                .filter(Video.storage_type == "remote")
                .filter(
                    or_(
                        Video.url.like("function/%"),
                        Video.url.like("%camwhores.tv/videos/%"),
                        Video.url.like("%pixeldrain.com/u/%"),
                        Video.url.like("%pixeldrain.com/l/%"),
                        Video.url.like("%https://%"),
                        Video.url.like("%http://%"),
                        Video.source_url.like("%camwhores.tv/videos/%"),
                        Video.source_url.like("%pixeldrain.com/u/%"),
                    )
                )
                .order_by(Video.id.desc())
                .limit(safe_limit)
                .all()
            )

            for v in candidates:
                scanned += 1
                if not _needs_repair(v):
                    continue
                queued += 1

                try:
                    if v.url:
                        m = re.search(r"https?://", v.url)
                        if m and m.start() > 0:
                            v.url = v.url[m.start():]
                            db_local.commit()

                    if (not v.source_url) and (
                        "camwhores.tv/videos/" in (v.url or "").lower()
                        or "pixeldrain.com/u/" in (v.url or "").lower()
                    ):
                        v.source_url = v.url
                        db_local.commit()

                    processor.process_single_video(v.id, force=True, extractor="auto")
                    repaired += 1
                except Exception as e:
                    failed += 1
                    logging.warning(f"[repair-import-streams] Failed video {v.id}: {e}")

            logging.info(
                f"[repair-import-streams] Done scanned={scanned}, queued={queued}, repaired={repaired}, failed={failed}"
            )
        finally:
            db_local.close()

    background_tasks.add_task(run_repair)
    return {
        "status": "started",
        "message": "Import stream repair started in background",
        "limit": safe_limit,
    }


@router.post("/maintenance/full-optimization")
async def full_optimization(background_tasks: BackgroundTasks):
    def run_optimization():
        db_local = SessionLocal()
        try:
            logging.info("Starting Full Library Optimization...")
            res1 = normalize_all_titles(db_local)
            compute_all_phashes(db_local)
            res2 = auto_resolve_duplicates(db_local, "name")
            res3 = auto_resolve_duplicates(db_local, "hash")
            logging.info(f"Optimization complete: {res1}, {res2}, {res3}")
        finally:
            db_local.close()

    background_tasks.add_task(run_optimization)
    return {"status": "started", "message": "Full library optimization started in background"}


@router.post("/maintenance/refresh-metadata")
def refresh_metadata_route(background_tasks: BackgroundTasks):
    def run_refresh():
        db = SessionLocal()
        try:
            refresh_poor_metadata(db)
        finally:
            db.close()

    background_tasks.add_task(run_refresh)
    return {"status": "started", "message": "Metadata refresh for incomplete videos started in background"}
