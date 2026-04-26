from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException, Request, Response, Body, WebSocket, WebSocketDisconnect, APIRouter, Header
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import distinct, desc, asc, or_
import re
import time
from typing import Any, List, Optional
from pydantic import BaseModel
import datetime
import os
from dotenv import load_dotenv

load_dotenv()
from .config import config
from .logging_setup import configure_logging

configure_logging(config.LOG_LEVEL, config.LOG_JSON)

import aiohttp
import httpx
import json
import base64
import urllib.parse
import requests
import shutil
import subprocess
import yt_dlp
import asyncio
import logging

from .database import get_db, init_db, Video, SmartPlaylist, SessionLocal, SearchHistory, DiscoveryProfile, DiscoveryNotification, DiscoveredVideo
# FIX: Odstránené nefunkčné importy (PornOne, JD)
from contextlib import asynccontextmanager
from .services import VIPVideoProcessor, search_videos_by_subtitle, get_batch_stats, get_tags_stats, get_quality_stats, extract_playlist_urls, fetch_eporner_videos, scrape_eporner_discovery
from .porntrex_discovery import scrape_porntrex_discovery
from .whoreshub_discovery import scrape_whoreshub_discovery
from .search_engine import ExternalSearchEngine
from .websockets import manager
import collections
from .telegram_auth import manager as tg_auth_manager
from pydantic import BaseModel
import collections
from archivist import Archivist
from .scheduler import init_scheduler, get_scheduler, shutdown_scheduler
from .auto_discovery import run_discovery_profile, get_worker

# Initialize Archivist
archivist = Archivist(download_dir="app/static/local_videos")


# --- WINDOWS ASYNCIO FIX ---
# Suppress known asyncio error in _ProactorBaseWritePipeTransport._loop_writing
# "AssertionError: assert f is self._write_fut"
import sys
if sys.platform == 'win32':
    try:
        from asyncio.proactor_events import _ProactorBaseWritePipeTransport
        _original_loop_writing = _ProactorBaseWritePipeTransport._loop_writing
        def _safe_loop_writing(self, *args, **kwargs):
            try:
                return _original_loop_writing(self, *args, **kwargs)
            except AssertionError:
                return None
        _ProactorBaseWritePipeTransport._loop_writing = _safe_loop_writing
    except (ImportError, AttributeError):
        pass
# ---------------------------




from app.http_client import get_http_session
http_session = None
# Env reload trigger 3

@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import http_client
    # Increase limits for many concurrent video streams
    # Use a robust resolver to handle domains with DNS issues (like nsfwclips.co)
    # Falls back to default resolver if aiodns/pycares DLL is blocked by OS policy
    try:
        resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "8.8.4.4", "1.1.1.1"])
        connector = aiohttp.TCPConnector(limit=200, limit_per_host=50, keepalive_timeout=60, resolver=resolver)
    except RuntimeError:
        print("WARNING: aiodns unavailable, using default resolver (DNS may be slower)")
        connector = aiohttp.TCPConnector(limit=200, limit_per_host=50, keepalive_timeout=60)
    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=600)
    http_client.http_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    print("AIOHTTP ClientSession created with increased limits.")
    
    # --- CLEANUP STUCK TASKS ON STARTUP ---
    try:
        db = SessionLocal()
        stuck_videos = db.query(Video).filter(or_(Video.status == 'processing', Video.status == 'downloading')).all()
        if stuck_videos:
            print(f"Startup: Resetting {len(stuck_videos)} stuck videos to 'error' state.")
            for v in stuck_videos:
                v.status = 'error' # Or 'ready' if we want to be optimistic, but 'error' prompts retry
            db.commit()
        db.close()
    except Exception as e:
        print(f"Startup cleanup error: {e}")
        
    # --- STARTUP LINK REFRESH (Always Live) ---
    async def refresh_video_link(video_id: int):
        """Refreshes the URL for a single video."""
        db = SessionLocal()
        try:
            v = db.query(Video).filter(Video.id == video_id).first()
            if not v or not v.source_url or v.storage_type != 'remote':
                return

            # Basic check if link is responsive
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                async with http_session.head(v.url, timeout=5, headers=headers, ssl=False) as r:
                    if r.status < 400:
                        v.last_checked = datetime.datetime.now()
                        db.commit()
                        return # Link is still good
            except Exception:
                pass # Link is not responsive, proceed to refresh

            print(f"Refreshing: {v.title} (ID: {v.id})")
            
            # --- ATTEMPT HEALING VIA CUSTOM EXTRACTORS ---
            try:
                from .extractors.registry import ExtractorRegistry
                # Ensure extractors are registered (they might not be if this is a fresh worker)
                from .extractors.bunkr import BunkrExtractor as NewBunkrExtractor
                if not ExtractorRegistry.find_extractor("https://bunkr.si/v/test"):
                    ExtractorRegistry.register(NewBunkrExtractor())
                
                # ... register others if needed ...

                plugin = ExtractorRegistry.find_extractor(v.source_url or v.url)
                if plugin:
                    print(f"Using plugin {plugin.name} to heal {v.id}")
                    res = await plugin.extract(v.source_url or v.url)
                    if res and res.get('stream_url'):
                        v.url = res['stream_url']
                        v.last_checked = datetime.datetime.now()
                        db.commit()
                        print(f"Successfully healed via plugin {plugin.name}: {v.title}")
                        return
            except Exception as pe:
                print(f"Plugin healing failed for {v.id}: {pe}")

            # --- FALLBACK TO YT-DLP ---
            try:
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                opts = {
                    'quiet': True, 'skip_download': True, 'format': 'best', 
                    'user_agent': user_agent,
                    'ignoreerrors': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': user_agent,
                        'Referer': v.source_url or "https://www.google.com/"
                    }
                }
                
                # Apply domain-specific cookies
                src_url = (v.source_url or "").lower()
                if "xvideos.com" in src_url and os.path.exists("xvideos.cookies.txt"):
                    opts['cookiefile'] = 'xvideos.cookies.txt'
                elif "eporner.com" in src_url and os.path.exists("eporner.cookies.txt"):
                    opts['cookiefile'] = 'eporner.cookies.txt'
                
                def get_info():
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        return ydl.extract_info(v.source_url or v.url, download=False)
                info = await asyncio.to_thread(get_info)
                if info and info.get('url'):
                    v.url = info['url']
                    v.last_checked = datetime.datetime.now()
                    db.commit()
                    print(f"Successfully refreshed via yt-dlp: {v.title}")
                else:
                    print(f"Could not get new URL for {v.title}")
            except Exception as e:
                db.rollback()
                print(f"Error refreshing {v.title}: {e}")
        except Exception as e:
            if "has been deleted" not in str(e):
                print(f"Error in refresh_video_link for video {video_id}: {e}")
        finally:
            db.close()

    async def refresh_links_task():
        """A background task that refreshes older links on startup to ensure they work."""
        await asyncio.sleep(5)  # Wait for full startup
        print("Startup: Link refresher started.")
        try:
            db_query = SessionLocal()
            # Get IDs of 100 oldest videos
            video_ids = [v[0] for v in db_query.query(Video.id).order_by(Video.last_checked.asc().nullsfirst()).limit(100).all()]
            db_query.close()
            
            if not video_ids:
                return

            print(f"Startup: Refreshing {len(video_ids)} oldest links...")
            for vid in video_ids:
                try:
                    await refresh_video_link(vid)
                    await asyncio.sleep(0.5) # Slight throttle
                except Exception as e:
                    if "has been deleted" not in str(e):
                        print(f"Error refreshing video {vid}: {e}")
            
            print("Startup: Link refresher finished.")
        except Exception as e:
            print(f"Link refresher loop error: {e}")

    # Disabled to speed up startup - can be manually triggered if needed
    # asyncio.create_task(refresh_links_task())
        
    # --- START WEBSOCKET PULSE & PUBSUB ---
    await manager.start_pubsub()

    async def pulse_task():
        while True:
            await asyncio.sleep(30)
            await manager.pulse()
    
    asyncio.create_task(pulse_task())

    # --- CONFIGURE GOFILE TOKEN ---
    gofile_token = config.GOFILE_TOKEN
    if gofile_token:
        try:
            from app.extractors.gofile import GoFileExtractor
            GoFileExtractor.set_user_token(gofile_token)
            print(f"GoFile user token configured (length: {len(gofile_token)})")
        except Exception as e:
            print(f"Failed to configure GoFile token: {e}")

    # --- INITIALIZE TASK SCHEDULER ---
    try:
        scheduler = init_scheduler()
        print("Task scheduler initialized")

        # Load and schedule all enabled discovery profiles
        db = SessionLocal()
        try:
            enabled_profiles = db.query(DiscoveryProfile).filter(DiscoveryProfile.enabled == True).all()
            for profile in enabled_profiles:
                try:
                    if profile.schedule_type == "interval":
                        interval_seconds = int(profile.schedule_value)
                        scheduler.add_interval_job(
                            run_discovery_profile,
                            job_id=f"profile_{profile.id}",
                            seconds=interval_seconds,
                            description=f"Discovery: {profile.name}",
                            args=(profile.id,)
                        )
                        print(f"Scheduled profile '{profile.name}' (every {interval_seconds}s)")
                    elif profile.schedule_type == "cron":
                        scheduler.add_cron_job(
                            run_discovery_profile,
                            job_id=f"profile_{profile.id}",
                            cron_expression=profile.schedule_value,
                            description=f"Discovery: {profile.name}",
                            args=(profile.id,)
                        )
                        print(f"Scheduled profile '{profile.name}' (cron: {profile.schedule_value})")
                except Exception as e:
                    print(f"Failed to schedule profile '{profile.name}': {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"Scheduler initialization error: {e}")

    yield

    # --- SHUTDOWN ---
    try:
        shutdown_scheduler(wait=True)
        print("Task scheduler shutdown")
    except Exception as e:
        print(f"Scheduler shutdown error: {e}")

    if http_session:
        await http_client.http_session.close() if http_client.http_session else None
        print("AIOHTTP ClientSession closed.")

app = FastAPI(title="Quantum VIP Dashboard", lifespan=lifespan)
init_db()

from app.models import *
# --- API ROUTING MODULARIZATION ---
api_v1_router = APIRouter(prefix="/api/v1")
from app.routers.api_v1_router import router as _modular_api_v1_router

# To preserve backwards compatibility for the moment
api_legacy_router = APIRouter(prefix="/api")
from app.routers import duplicates, library_health, maintenance_endpoints, smart_playlists, semantic_search

for _r in (
    duplicates.router,
    library_health.router,
    maintenance_endpoints.router,
    smart_playlists.router,
    semantic_search.router,
):
    api_legacy_router.include_router(_r)

@api_legacy_router.post("/webshare/search")
@api_v1_router.post("/webshare/search")
async def search_webshare(req: WebshareSearchRequest):
    """
    Search Webshare for files and return results sorted by quality (size).
    """
    try:
        from extractors.webshare import WebshareAPI
        # We can eventually load token from .env or DB settings if we want protected files
        ws = WebshareAPI(token=None) 
        
        # Run synchronous request in thread pool
        # Pass sort parameter to search_files
        search_resp = await asyncio.to_thread(ws.search_files, req.query, req.limit, req.sort, req.offset)
        
        results = search_resp.get('results', [])
        total_count = search_resp.get('total', 0)
        
        # Filter results by size if requested
        if req.min_size or req.max_size:
            filtered = []
            for r in results:
                size = r.get('size_bytes', 0)
                if req.min_size and size < req.min_size: continue
                if req.max_size and size > req.max_size: continue
                filtered.append(r)
            results = filtered
            
        return {"status": "success", "results": results, "total": total_count}
    except Exception as e:
        print(f"Webshare API endpoint error: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@api_v1_router.post("/webshare/import")
@api_legacy_router.post("/webshare/import")
async def import_webshare(url: str = Body(..., embed=True), batch_name: str = Body(None), db: Session = Depends(get_db)):
    """
    Import a video directly from a Webshare link string, create Video entry, trigger processing, and return status.
    """
    try:
        # 1. Create Video entry
        from .database import Video
        video = Video(
            url=url,
            source_url=url,
            title="Webshare import",
            status="queued",
            batch_name=batch_name or "Webshare Import",
            storage_type="remote"
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        # 2. Trigger processing (VIP link, thumbnail, etc.)
        from app.workers.tasks import process_video_task
        process_video_task.delay(video.id)

        return {"status": "success", "video_id": video.id}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# --- Password & Session ---
DASHBOARD_PASSWORD = config.DASHBOARD_PASSWORD
SECRET_KEY = config.SECRET_KEY

from fastapi.middleware.cors import CORSMiddleware
from .middleware_request_id import RequestIdMiddleware

# Starlette: last add_middleware = outermost = runs first on incoming request.
# RequestId must be added last so request_id is set before Session/CORS run.
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
_cors_kw = {
    "allow_origins": config.CORS_ORIGINS,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
_cors_kw["allow_credentials"] = False if config.CORS_ORIGINS == ["*"] else True
app.add_middleware(CORSMiddleware, **_cors_kw)
app.add_middleware(RequestIdMiddleware)


app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- Models ---
# --- Routes ---

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

class LoginRequest(BaseModel):
    password: str

@app.post("/login")
async def login_submit(request: Request, login_request: LoginRequest):
    if login_request.password == DASHBOARD_PASSWORD:
        request.session["authenticated"] = True
        return Response(status_code=200)
    raise HTTPException(status_code=401, detail="Invalid password")

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("authenticated", None)
    return RedirectResponse(url="/login")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/discovery", response_class=HTMLResponse)
async def discovery_page(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("discovery.html", {"request": request})

@app.get("/discovery/review/{profile_id}", response_class=HTMLResponse)
async def discovery_review_page(request: Request, profile_id: int):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("discovery_review.html", {"request": request, "profile_id": profile_id})

@app.get("/v2", response_class=HTMLResponse)
async def read_v2(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
# This route can be used to directly preview the V2 UI
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/stats", response_class=HTMLResponse)
async def get_stats_page(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("stats.html", {"request": request})

@app.get("/favicon.ico")
def favicon(): return Response(status_code=204)

@app.post("/api/v1/pornhoarder/update_stream")
@app.post("/api/v1/videos/update_stream")
async def pornhoarder_update_stream(payload: dict, db: Session = Depends(get_db)):
    """Receives direct stream URL from PornHoarder browser interceptor content script."""
    source_url = (payload.get("source_url") or "").strip()
    stream_url = (payload.get("stream_url") or "").strip()
    source = (payload.get("source") or "pornhoarder").strip().lower()
    title = (payload.get("title") or "").strip()

    def _title_from_source(url: str) -> str:
        try:
            from urllib.parse import urlparse, unquote
            path = urlparse(url or "").path
            # /watch/<slug>/<token>
            parts = [p for p in path.split("/") if p]
            if "watch" in parts:
                i = parts.index("watch")
                if i + 1 < len(parts):
                    return unquote(parts[i + 1]).replace("-", " ").strip().title()
            if parts:
                return unquote(parts[-1]).replace("-", " ").strip().title()
        except Exception:
            pass
        return ""

    if not source_url or not stream_url:
        return {"status": "error", "message": "missing fields"}

    def _looks_like_stream(url: str) -> bool:
        u = (url or "").strip().lower()
        if not u.startswith(("http://", "https://")):
            return False
        return (
            bool(re.search(r"\.(mp4|m3u8|mpd)(\?|$)", u))
            or "/api/v1/proxy/hls?url=" in u
            or "/hls_proxy?url=" in u
        )

    resolved_stream = stream_url
    resolved_title = title
    resolved_thumbnail = ""
    resolved_duration = 0
    resolved_player_url = ""

    # For browser-captured providers, try extractor once:
    # - resolves non-playable captures/player URLs to direct streams
    # - fills metadata for clean dashboard cards.
    if source in ("pornhoarder", "recurbate"):
        try:
            if source == "pornhoarder":
                from .extractors.pornhoarder import PornHoarderExtractor
                extractor = PornHoarderExtractor()
            else:
                from .extractors.recurbate import RecurbateExtractor
                extractor = RecurbateExtractor()
            extracted = asyncio.run(extractor.extract(source_url))
            if extracted:
                candidate = (extracted.get("stream_url") or "").strip()
                if (
                    candidate and
                    _looks_like_stream(candidate) and
                    "player.php" not in candidate.lower() and
                    (not _looks_like_stream(stream_url) or "player.php" in stream_url.lower())
                ):
                    resolved_stream = candidate
                resolved_title = resolved_title or (extracted.get("title") or "").strip()
                resolved_thumbnail = (extracted.get("thumbnail") or "").strip()
                resolved_duration = int(extracted.get("duration") or 0)
                resolved_player_url = (extracted.get("player_url") or "").strip()
        except Exception as exc:
            logging.warning(f"[StreamCapture] stream resolve failed for {source_url}: {exc}")

    if not _looks_like_stream(resolved_stream):
        logging.warning(f"[PH-Interceptor] Rejected non-playable stream URL: {resolved_stream[:120]}")
        return {"status": "error", "message": "non_playable_stream", "stream_url": resolved_stream[:200]}

    def _queue_thumbnail_processing(video_id: int) -> None:
        try:
            processor = VIPVideoProcessor()
            import threading
            threading.Thread(
                target=processor.process_single_video,
                args=(video_id,),
                daemon=True,
            ).start()
        except Exception as exc:
            logging.warning(f"[PH-Interceptor] Failed to queue thumbnail processing for {video_id}: {exc}")

    video = db.query(Video).filter(Video.source_url == source_url).order_by(Video.id.desc()).first()
    if not video:
        video = db.query(Video).filter(Video.url == source_url).order_by(Video.id.desc()).first()
    if video:
        logging.info(f"[PH-Interceptor] Updating stream for video {video.id}: {resolved_stream[:80]}")
        video.url = resolved_stream
        video.status = "ready_to_stream"
        if resolved_title and (not video.title or str(video.title).lower().startswith(("untitled", "queued"))):
            video.title = resolved_title
        if resolved_duration > 0 and not (video.duration or 0):
            video.duration = float(resolved_duration)
        if resolved_thumbnail and not video.thumbnail_path:
            video.thumbnail_path = resolved_thumbnail
        if resolved_player_url:
            stats = video.download_stats or {}
            stats["player_url"] = resolved_player_url
            video.download_stats = stats
            try:
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(video, "download_stats")
            except Exception:
                pass
        db.commit()
        # Ensure preview thumbnail is generated for interceptor-only entries.
        if not video.thumbnail_path:
            _queue_thumbnail_processing(video.id)
        return {"status": "ok", "video_id": video.id}
    logging.info(f"[PH-Interceptor] No video found for source_url, creating new one: {source_url}")
    new_video = Video(
        title=resolved_title or _title_from_source(source_url) or f"{source.capitalize()} Video",
        url=resolved_stream,
        source_url=source_url,
        thumbnail_path=resolved_thumbnail or None,
        duration=float(resolved_duration or 0),
        height=0,
        width=0,
        batch_name=f"{source.capitalize()} Interceptor",
        tags=source,
        storage_type="remote",
        status="ready_to_stream",
        download_stats=({"player_url": resolved_player_url} if resolved_player_url else None),
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)
    _queue_thumbnail_processing(new_video.id)
    return {"status": "created", "video_id": new_video.id}


@app.get("/health")
def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "Quantum VIP Dashboard", "timestamp": datetime.datetime.utcnow().isoformat()}

@app.get("/health/db")
def health_check_db():
    """Database health check with detailed statistics."""
    from .database import get_db_health, get_migration_version
    
    db_health = get_db_health()
    migration_info = get_migration_version()
    
    return {
        "database": db_health,
        "migrations": migration_info,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

@app.get("/health/pool")
def health_check_pool():
    """Connection pool statistics."""
    from .database import engine
    
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in_connections": pool.checkedin(),
        "checked_out_connections": pool.checkedout(),
        "overflow_connections": pool.overflow(),
        "max_overflow": pool._max_overflow if hasattr(pool, '_max_overflow') else 0,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }


@api_v1_router.get("/videos")
@api_legacy_router.get("/videos")
def get_videos(page: int = 1, limit: int = 10, search: str = "", batch: str = "All", favorites_only: bool = False, quality: str = "All", duration_min: int = 0, duration_max: int = 99999, sort: str = "date_desc", dateMin: Optional[str] = None, dateMax: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Video)
    # Filter out videos without titles to prevent frontend errors
    query = query.filter(Video.title != None, Video.title != "")
    if search: query = query.filter(or_(Video.title.contains(search), Video.tags.contains(search), Video.ai_tags.contains(search), Video.batch_name.contains(search)))
    if batch and batch != "All": query = query.filter(Video.batch_name == batch)
    if favorites_only: query = query.filter(Video.is_favorite == True)
    query = query.filter(Video.duration >= duration_min)
    if duration_max < 3600: query = query.filter(Video.duration <= duration_max)
    if quality != "All":
        if quality == "4K": query = query.filter(Video.height >= 2160)
        elif quality == "1440p": query = query.filter(Video.height >= 1440, Video.height < 2160)
        elif quality in ["1080p", "FHD"]: query = query.filter(Video.height >= 1080, Video.height < 1440)
        elif quality in ["720p", "HD"]: query = query.filter(Video.height >= 720, Video.height < 1080)
        elif quality == "SD": query = query.filter(Video.height < 720)
    
    if dateMin:
        try: query = query.filter(Video.created_at >= datetime.datetime.fromisoformat(dateMin))
        except ValueError: pass
    if dateMax:
        try: query = query.filter(Video.created_at < datetime.datetime.fromisoformat(dateMax) + datetime.timedelta(days=1))
        except ValueError: pass

    if sort == "date_desc": query = query.order_by(desc(Video.id))
    elif sort == "title_asc": query = query.order_by(asc(Video.title))
    elif sort == "longest": query = query.order_by(desc(Video.duration))
    elif sort == "shortest": query = query.order_by(asc(Video.duration))
    
    videos = query.offset((page - 1) * limit).limit(limit).all()
    
    # Note: Beeg video auto-refresh was removed from GET /videos to prevent thread spam and NameErrors.
    # Link refresh should be handled via a dedicated scheduled task or JIT during playback.
    
    # Convert to dicts and add gif_preview_path
    results = []
    for v in videos:
        video_dict = v.__dict__
        video_dict.pop('_sa_instance_state', None) # Remove SQLAlchemy state
        # Double-check title exists before adding to results
        if video_dict.get('title'):
            results.append(video_dict)
        
    return results

@api_v1_router.get("/export")
@api_legacy_router.get("/export")
def export_videos(search: str = "", batch: str = "All", favorites_only: bool = False, quality: str = "All", duration_min: int = 0, duration_max: int = 99999, sort: str = "date_desc", dateMin: Optional[str] = None, dateMax: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Video)
    if search: query = query.filter(or_(Video.title.contains(search), Video.tags.contains(search), Video.ai_tags.contains(search), Video.batch_name.contains(search)))
    if batch and batch != "All": query = query.filter(Video.batch_name == batch)
    if favorites_only: query = query.filter(Video.is_favorite == True)
    query = query.filter(Video.duration >= duration_min)
    if duration_max < 3600: query = query.filter(Video.duration <= duration_max)
    if quality != "All":
        if quality == "4K": query = query.filter(Video.height >= 2160)
        elif quality == "1440p": query = query.filter(Video.height >= 1440, Video.height < 2160)
        elif quality in ["1080p", "FHD"]: query = query.filter(Video.height >= 1080, Video.height < 1440)
        elif quality in ["720p", "HD"]: query = query.filter(Video.height >= 720, Video.height < 1080)
        elif quality == "SD": query = query.filter(Video.height < 720)
    
    if dateMin:
        try: query = query.filter(Video.created_at >= datetime.datetime.fromisoformat(dateMin))
        except ValueError: pass
    if dateMax:
        try: query = query.filter(Video.created_at < datetime.datetime.fromisoformat(dateMax) + datetime.timedelta(days=1))
        except ValueError: pass

    if sort == "date_desc": query = query.order_by(desc(Video.id))
    elif sort == "title_asc": query = query.order_by(asc(Video.title))
    elif sort == "longest": query = query.order_by(desc(Video.duration))
    elif sort == "shortest": query = query.order_by(asc(Video.duration))
    
    videos = query.all()
    content = [VideoExport.from_orm(v).dict() for v in videos]
    return JSONResponse(content=content, headers={'Content-Disposition': f'attachment; filename="export.json"'})

@api_v1_router.get("/search/subtitles")
@api_legacy_router.get("/search/subtitles")
def search_subs(query: str, db: Session = Depends(get_db)):
    return search_videos_by_subtitle(query, db)

@api_v1_router.get("/search/external")
@api_legacy_router.get("/search/external")
async def search_external(query: str, source: Optional[str] = None):
    """
    Search external sources (SimpCity, Telegram, etc.) for media content.
    Returns aggregated results from all available sources.
    """
    if not query or len(query.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")
    
    try:
        engine = ExternalSearchEngine()
        results = await engine.search(query.strip(), source=source)
        
        # Save to history
        db = next(get_db())
        try:
            history_entry = SearchHistory(
                query=query.strip(),
                source="Quantum",
                results_count=len(results)
            )
            db.add(history_entry)
            db.commit()
        except Exception as ex:
            print(f"Failed to save search history: {ex}")
        
        return {
            "query": query,
            "total_results": len(results),
            "sources": list(set(r['source'] for r in results)),
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
    
@api_v1_router.get("/batches")
@api_legacy_router.get("/batches")
def get_batches(db: Session = Depends(get_db), sort: str = "name", detailed: bool = False):
    """Get all batches with optional sorting

    Args:
        sort: Sorting method - 'name' (alphabetical), 'newest' (most recent video), 'biggest' (video count)
        detailed: If True, return detailed batch info (name, size, import_date)
    """
    from sqlalchemy import func

    # Get all videos with their batch and stats to calculate total size accurately
    all_videos = db.query(Video.batch_name, Video.download_stats, Video.created_at).filter(Video.batch_name.isnot(None)).all()
    
    batch_stats = {}
    for batch_name, d_stats, created_at in all_videos:
        if not batch_name: continue
        if batch_name not in batch_stats:
            batch_stats[batch_name] = {
                'count': 0, 
                'total_size_mb': 0.0, 
                'first_import': created_at, 
                'last_import': created_at
            }
        
        s = batch_stats[batch_name]
        s['count'] += 1
        if d_stats and isinstance(d_stats, dict) and d_stats.get('size_mb'):
            s['total_size_mb'] += float(d_stats['size_mb'])
        
        if created_at:
            if not s['first_import'] or created_at < s['first_import']:
                s['first_import'] = created_at
            if not s['last_import'] or created_at > s['last_import']:
                s['last_import'] = created_at

    # Convert to list of dicts with metadata
    batches_with_info = []
    for name, s in batch_stats.items():
        total_mb = round(s['total_size_mb'], 2)
        batches_with_info.append({
            'name': name,
            'size': s['count'], # For backwards compatibility (represents video count)
            'total_size_mb': total_mb,
            'size_text': f"{total_mb / 1024:.1f} GB" if total_mb > 1024 else f"{int(total_mb)} MB",
            'import_date': s['first_import'].isoformat() if s['first_import'] else None,
            'last_updated': s['last_import'].isoformat() if s['last_import'] else None
        })

    # Apply sorting
    if sort == "name":
        batches_with_info.sort(key=lambda x: x['name'])
    elif sort == "newest":
        batches_with_info.sort(key=lambda x: x['last_updated'] or '', reverse=True)
    elif sort == "biggest":
        batches_with_info.sort(key=lambda x: x['size'], reverse=True)
    elif sort == "size": # Actual file size
        batches_with_info.sort(key=lambda x: x['total_size_mb'], reverse=True)
    else:
        batches_with_info.sort(key=lambda x: x['name'])

    # Return detailed info if requested, otherwise just names for backwards compatibility
    if detailed:
        return batches_with_info
    else:
        return [b['name'] for b in batches_with_info]

@api_v1_router.get("/tags")
@api_legacy_router.get("/tags")
def get_all_tags(db: Session = Depends(get_db)):
    all_tags = set()
    videos = db.query(Video.tags, Video.ai_tags).filter(or_(Video.tags != None, Video.ai_tags != None)).all()
    for video_tags, video_ai_tags in videos:
        if video_tags: all_tags.update(tag.strip() for tag in video_tags.split(',') if tag.strip())
        if video_ai_tags: all_tags.update(tag.strip() for tag in video_ai_tags.split(',') if tag.strip())
    return sorted(list(all_tags))

# --- Config Endpoints ---
@api_v1_router.get("/config/gofile_token")
@api_legacy_router.get("/config/gofile_token")
async def get_gofile_token():
    """Return the configured GoFile user token so extensions can reuse it."""
    from .extractors.gofile import GoFileExtractor
    token = GoFileExtractor._user_token or (config.GOFILE_TOKEN or "")
    return {"token": token}

# --- Stats Endpoints ---
@api_v1_router.get("/stats/batches")
@api_legacy_router.get("/stats/batches")
def api_get_batch_stats(db: Session = Depends(get_db)): return get_batch_stats(db)

@api_v1_router.get("/stats/tags")
@api_legacy_router.get("/stats/tags")
def api_get_tags_stats(db: Session = Depends(get_db)): return get_tags_stats(db)

@api_v1_router.get("/stats/quality")
@api_legacy_router.get("/stats/quality")
def api_get_quality_stats(db: Session = Depends(get_db)): return get_quality_stats(db)

@api_v1_router.get("/search/history")
@api_legacy_router.get("/search/history")
def get_search_history(limit: int = 10, db: Session = Depends(get_db)):
    return db.query(SearchHistory).order_by(desc(SearchHistory.created_at)).limit(limit).all()



def refresh_video_link(video_id: int):
    """Refresh a single video's link by re-extracting from source_url"""
    db = SessionLocal()
    try:
        v = db.query(Video).get(video_id)
        if not v or not v.source_url:
            return
        
        # For XVideos, use the dedicated extractor which prioritizes HLS quality
        if 'xvideos.com' in v.source_url:
            processor = VIPVideoProcessor()
            meta = processor.extract_xvideos_metadata(v.source_url)
            if meta and meta.get('stream') and meta['stream'].get('url'):
                v.url = meta['stream']['url']
                if meta['stream'].get('height'):
                    v.height = meta['stream']['height']
                db.commit()
                logging.info(f"Refreshed link for video {video_id}")
                return
        
        # Beeg Refresh Support - URLs expire quickly
        if 'beeg.com' in (v.source_url or ""):
            try:
                import subprocess
                
                # Use fast refresh script
                cmd = [sys.executable, "beeg_refresh.py", v.source_url]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    new_stream_url = result.stdout.strip()
                    
                    if new_stream_url and new_stream_url.startswith('http'):
                        # Parse HLS if needed
                        if 'multi=' in new_stream_url:
                            import aiohttp
                            async def get_best_quality():
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(new_stream_url) as resp:
                                        if resp.status == 200:
                                            playlist = await resp.text()
                                            lines = playlist.split('\n')
                                            best_url = None
                                            best_bandwidth = 0
                                            
                                            for i, line in enumerate(lines):
                                                if line.startswith('#EXT-X-STREAM-INF'):
                                                    bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                                                    if bw_match and i + 1 < len(lines):
                                                        bandwidth = int(bw_match.group(1))
                                                        url = lines[i + 1].strip()
                                                        if url and bandwidth > best_bandwidth:
                                                            best_bandwidth = bandwidth
                                                            if not url.startswith('http'):
                                                                base = '/'.join(new_stream_url.split('/')[:-1])
                                                                best_url = f"{base}/{url}"
                                                            else:
                                                                best_url = url
                                            return best_url
                                return None
                            
                            # Run async function
                            import asyncio
                            best_url = asyncio.run(get_best_quality())
                            if best_url:
                                new_stream_url = best_url
                        
                        v.url = new_stream_url
                        v.last_checked = datetime.datetime.now()
                        db.commit()
                        logging.info(f"Refreshed Beeg link for video {video_id}")
                        return
            except Exception as e:
                logging.error(f"Beeg refresh failed: {e}")
        
        # Webshare Refresh Support
        if 'webshare.cz' in (v.source_url or "") or 'wsfiles.cz' in (v.source_url or "") or (v.url and v.url.startswith("webshare:")):
            try:
                from extractors.webshare import WebshareAPI
                ws = WebshareAPI()
                ident = None
                
                # Try to find ident
                src = v.source_url or v.url
                if src.startswith("webshare:"):
                    ident = src.split(":", 2)[1]
                elif "/file/" in src:
                    part = src.split('/file/')[1]
                    ident = part.split('/')[0] if '/' in part else part
                
                if not ident and 'wsfiles.cz' in src:
                     parts = src.split('/')
                     for p in parts:
                         if len(p) == 10 and p.isalnum() and not p.isdigit():
                             ident = p
                             break
                
                if ident:
                    new_link = ws.get_vip_link(ident)
                    if new_link:
                        v.url = new_link
                        db.commit()
                        logging.info(f"Refreshed Webshare link for video {video_id}")
                        return
            except Exception as e:
                logging.error(f"Webshare refresh failed: {e}")

        # For other sources, use standard extraction
        cookie_file = 'xvideos.cookies.txt' if 'xvideos.com' in v.source_url else None
        is_deep = 'xvideos.com' in v.source_url or 'xhamster.com' in v.source_url or 'eporner.com' in v.source_url
        opts = {
            'quiet': True, 'skip_download': True, 
            # Prioritize HLS for best quality
            'format': 'best[protocol*=m3u8]/best[ext=mp4]/best',
            'extract_flat': False if is_deep else True
        }
        if cookie_file and os.path.exists(cookie_file):
            opts['cookiefile'] = cookie_file
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(v.source_url, download=False)
        
        if info and info.get('url'):
            v.url = info['url']
            # Update height if available
            if info.get('height'):
                v.height = info['height']
            db.commit()
            logging.info(f"Refreshed link for video {video_id}")
    except Exception as e:
        logging.error(f"Failed to refresh link for video {video_id}: {e}")
        db.rollback()
    finally:
        db.close()

@api_v1_router.post("/batch-action")
@api_legacy_router.post("/batch-action")
def batch_action(req: BatchActionRequest, bg_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    query = db.query(Video).filter(Video.id.in_(req.video_ids))
    if req.action == 'delete': query.delete(synchronize_session=False)
    elif req.action == 'favorite': query.update({Video.is_favorite: True}, synchronize_session=False)
    elif req.action == 'unfavorite': query.update({Video.is_favorite: False}, synchronize_session=False)
    elif req.action == 'mark_watched': query.update({Video.is_watched: True}, synchronize_session=False)
    elif req.action == 'refresh_links':
        from app.workers.tasks import refresh_video_link_task
        video_ids = req.video_ids.copy()
        for video_id in video_ids:
            refresh_video_link_task.delay(video_id)
        db.commit()
        return {"status": "ok", "message": f"Refreshing links for {len(video_ids)} videos in background"}
    
    db.commit()
    return {"status": "ok"}

@api_v1_router.post("/batch/refresh")
@api_legacy_router.post("/batch/refresh")
def refresh_entire_batch(req: BatchRefreshRequest, bg_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Refresh all video links for an entire batch in the background.
    """
    if not req.batch_name or req.batch_name == "All":
        raise HTTPException(status_code=400, detail="A specific batch name is required.")
    
    video_ids_query = db.query(Video.id).filter(Video.batch_name == req.batch_name).all()
    video_ids = [v_id for v_id, in video_ids_query]

    if not video_ids:
        return {"status": "ok", "message": "No videos found in this batch."}

    from app.workers.tasks import refresh_video_link_task
    for video_id in video_ids:
        refresh_video_link_task.delay(video_id)
    
    logging.info(f"Queued link refresh for {len(video_ids)} videos in batch '{req.batch_name}'.")
    
    return {"status": "ok", "message": f"Refreshing links for {len(video_ids)} videos in batch '{req.batch_name}' in the background."}


@api_v1_router.post("/batch/delete-all")
@api_legacy_router.post("/batch/delete-all")
def delete_entire_batch(req: BatchDeleteRequest, db: Session = Depends(get_db)):
    if not req.batch_name or req.batch_name == "All": raise HTTPException(400)
    db.query(Video).filter(Video.batch_name == req.batch_name).delete(synchronize_session=False)
    db.commit()
    return {"status": "deleted", "batch": req.batch_name}

@api_v1_router.put("/videos/{video_id}")
@api_legacy_router.put("/videos/{video_id}")
def update_video(video_id: int, update: VideoUpdate, db: Session = Depends(get_db)):
    v = db.query(Video).get(video_id)
    if not v: raise HTTPException(404)
    if update.is_favorite is not None: v.is_favorite = update.is_favorite
    if update.is_watched is not None: v.is_watched = update.is_watched
    if update.resume_time is not None: v.resume_time = update.resume_time
    if update.tags is not None: v.tags = update.tags
    if update.url is not None and update.url.startswith("http"):
        logging.info("[URL-push] video %s url updated by extension: %s", video_id, update.url[:100])
        v.url = update.url
    db.commit()
    return v

@api_v1_router.post("/videos/{video_id}/regenerate")
@api_legacy_router.post("/videos/{video_id}/regenerate")
def regenerate_thumbnail(video_id: int, bg_tasks: BackgroundTasks, mode: str = "mp4", extractor: str = "auto", db: Session = Depends(get_db)):
    v = db.query(Video).get(video_id)
    if not v: raise HTTPException(404)
    v.status = "pending"
    v.error_msg = None
    db.commit()
    from app.workers.tasks import process_video_task
    process_video_task.delay(video_id, force=True, quality_mode=mode, extractor=extractor)
    return {"status": "queued", "id": video_id}

@api_v1_router.post("/videos/{video_id}/refresh")
@api_legacy_router.post("/videos/{video_id}/refresh")
def refresh_video_url(video_id: int, db: Session = Depends(get_db)):
    """Refresh video URL (useful for Beeg and other sources with expiring links)"""
    v = db.query(Video).get(video_id)
    if not v: raise HTTPException(404)
    
    from app.workers.tasks import refresh_video_link_task
    refresh_video_link_task.delay(video_id)
    
    return {"status": "refreshing", "id": video_id, "message": "Link refresh started"}

import re

# ... existing code ...

active_downloads = {}

# --- BRIDGE EXTENSION ENDPOINTS ---

class BridgeSyncRequest(BaseModel):
    url: str
    cookies: Optional[str] = None
    user_agent: Optional[str] = None
    html_content: Optional[str] = None

def ensure_bridge_token(x_nexus_token: Optional[str]) -> None:
    """If NEXUS_BRIDGE_TOKEN is configured, require matching X-Nexus-Token header."""
    required_token = config.NEXUS_BRIDGE_TOKEN
    if not required_token:
        return
    if not x_nexus_token or x_nexus_token.strip() != required_token:
        raise HTTPException(status_code=401, detail="Invalid bridge token")

@api_v1_router.get("/bridge/ping")
@api_legacy_router.get("/bridge/ping")
async def bridge_ping(x_nexus_token: Optional[str] = Header(default=None, alias="X-Nexus-Token")):
    ensure_bridge_token(x_nexus_token)
    return {"status": "ok", "service": "bridge"}

@api_v1_router.post("/bridge/sync")
@api_legacy_router.post("/bridge/sync")
async def bridge_sync(req: BridgeSyncRequest, x_nexus_token: Optional[str] = Header(default=None, alias="X-Nexus-Token")):
    """
    Receives session data (cookies, ua) from Chrome Extension.
    Saves to domain-specific cookie files.
    """
    domain = urllib.parse.urlparse(req.url).netloc
    
    # Security: whitelist allowed domains to prevent cookie dumping abuse
    # For now allow all, but good to keep in mind
    ensure_bridge_token(x_nexus_token)
    
    if req.cookies:
        # Simple heuristic to map domain to cookie filename
        filename = "cookies.txt" # Default
        if "bunkr" in domain: filename = "bunkr.cookies.txt"
        elif "xvideos" in domain: filename = "xvideos.cookies.txt"
        elif "simpcity" in domain: filename = "simpcity.cookies.txt"
        
        # Save cookies in Netscape format (simplified) or raw header format
        # yt-dlp prefers Netscape, but raw header file also works if passed as --add-header
        # We will save as raw key=value string for requests lib and maybe convert for yt-dlp later
        # Actually, for this prototype, we just save the 'Cookie' header string to a file
        # that our Extractors can read and inject into requests headers.
        
        with open(filename, 'w') as f:
            f.write(req.cookies)
            
        # --- CONVERT TO NETSCAPE FOR YT-DLP ---
        try:
            netscape_name = filename.replace(".cookies.txt", ".netscape.txt") if ".cookies.txt" in filename else "cookies.netscape.txt"
            with open(netscape_name, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                # Domain should start with . for wildcards
                dot_domain = f".{domain}" if not domain.startswith(".") else domain
                # Format: domain, flag, path, secure, expiration, name, value
                # Since we have raw string "a=b; c=d", we split and guess
                pairs = [p.strip() for p in req.cookies.split(';') if '=' in p]
                expiry = str(int(datetime.datetime.now().timestamp()) + 86400 * 30) # +30 days
                for p in pairs:
                    name, val = p.split('=', 1)
                    f.write(f"{dot_domain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{val}\n")
            logging.info(f"Bridge: Converted to Netscape: {netscape_name}")
        except Exception as e:
            logging.error(f"Cookie conversion failed: {e}")

        logging.info(f"Bridge: Saved cookies for {domain} to {filename}")

    return {"status": "synced", "domain": domain}

class BridgeImportRequest(BaseModel):
    urls: List[str]
    batch_name: str = "Bridge Import"
    cookies: Optional[str] = None # Optional overriding cookies

@api_v1_router.post("/bridge/import")
@api_legacy_router.post("/bridge/import")
async def bridge_import(req: BridgeImportRequest, bg_tasks: BackgroundTasks, x_nexus_token: Optional[str] = Header(default=None, alias="X-Nexus-Token")):
    """
    Import URLs specifically from the extension, possibly with fresh cookies.
    """
    ensure_bridge_token(x_nexus_token)
    if req.cookies:
         # If import request comes with cookies (e.g. from Bunkr album page)
         # Save them generically as 'latest_bridge.cookies.txt'
         with open("bridge.cookies.txt", "w") as f:
             f.write(req.cookies)
    
    bg_tasks.add_task(background_import_process, req.urls, req.batch_name, "yt-dlp", None, None, None, True)
    return {"status": "ok", "count": len(req.urls)}


class BulkImportVideo(BaseModel):
    url: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    thumbnail: Optional[str] = None
    filesize: Optional[Any] = 0
    quality: Optional[Any] = 0  # may arrive as "720p", "HD", or int
    duration: Optional[Any] = 0  # may arrive as "0:16" string or seconds float
    tags: Optional[str] = ""

    def quality_px(self) -> int:
        q = self.quality
        if isinstance(q, int): return q
        if isinstance(q, float): return int(q)
        if isinstance(q, str):
            m = re.search(r'\d+', q)
            return int(m.group()) if m else 0
        return 0

    def duration_secs(self) -> float:
        d = self.duration
        if isinstance(d, (int, float)): return float(d)
        if isinstance(d, str):
            parts = [p for p in d.replace(',', ':').split(':') if p.strip()]
            try:
                parts = [int(x) for x in parts]
                if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
                if len(parts) == 2: return parts[0]*60 + parts[1]
                if len(parts) == 1: return float(parts[0])
            except: pass
        return 0.0

    def filesize_bytes(self) -> int:
        s = self.filesize
        if isinstance(s, (int, float)):
            return int(s)
        if isinstance(s, str):
            t = s.strip().upper().replace(",", ".")
            try:
                m = re.search(r"([\d.]+)\s*(TB|GB|MB|KB|B)?", t)
                if not m:
                    return int(float(re.sub(r"[^\d.]", "", t)))
                val = float(m.group(1))
                unit = (m.group(2) or "B").upper()
                mult = {
                    "B": 1,
                    "KB": 1024,
                    "MB": 1024 * 1024,
                    "GB": 1024 * 1024 * 1024,
                    "TB": 1024 * 1024 * 1024 * 1024,
                }
                return int(val * mult.get(unit, 1))
            except Exception:
                return 0
        return 0

class BulkImportRequest(BaseModel):
    batch_name: str = "Bulk Import"
    videos: List[BulkImportVideo]

@app.api_route("/stream_proxy/{video_id}.mp4", methods=["GET", "HEAD"])
async def proxy_video(video_id: str, request: Request, url: Optional[str] = None, db: Session = Depends(get_db)):
    v = None
    if url:
        # Generic URL proxying for search previews etc.
        target_url = url
        v_source_url = url
    else:
        v = db.query(Video).get(video_id)
        if not v: raise HTTPException(404)
        target_url = v.url
        v_source_url = v.source_url
    _cw_match = re.search(r"/videos/(\d+)", str(v_source_url or "") + " " + str(target_url or ""), re.I)
    cw_corr = f"cw:{_cw_match.group(1)}" if _cw_match else "cw:unknown"

    if not target_url:
        logging.error(f"Stream proxy requested for video {video_id} but target_url is empty")
        raise HTTPException(400, detail="Video URL is missing in the database. The video might be from a broken source.")

    # --- URL SANITIZATION ---
    # Strip malformed prefixes that can end up in the DB (e.g. "function/0/https://...")
    import re as _re
    _http_match = _re.search(r'https?://', target_url)
    if _http_match and _http_match.start() > 0:
        original_url = target_url
        target_url = target_url[_http_match.start():]
        logging.warning(f"Stripped malformed prefix from video {video_id} URL: '{original_url[:40]}' → '{target_url[:60]}'")
        if v:
            try:
                v.url = target_url
                db.commit()
                logging.info(f"Auto-healed URL in DB for video {video_id}")
            except Exception as _e:
                logging.warning(f"Could not auto-heal DB URL: {_e}")

    if not target_url.startswith(('http://', 'https://')):
        logging.error(f"Proxy attempt with non-HTTP URL for video {video_id}: '{target_url}'")
        raise HTTPException(500, detail=f"Invalid protocol or empty URL for proxy. Got: '{target_url}'")

    # --- OPTIMISTIC STREAMING (Fix for single-use tokens) ---
    range_header = request.headers.get('Range')

    # --- CAMWHORES: rnd=<unix_ms> is required for many get_file URLs (extension always includes it).
    if "camwhores" in target_url and "get_file" in target_url:
        from .extractors.camwhores import normalize_camwhores_get_file_rnd

        target_url = normalize_camwhores_get_file_rnd(target_url)

    async def get_request_params(v_url, ref_url):
        domain = urllib.parse.urlparse(v_url).netloc
        # Safe default: use the target stream domain as referer.
        # Site-specific branches below can override this when needed.
        referer = f"https://{domain}/"
        origin = None
        if "webshare.cz" in v_url or "wsfiles.cz" in v_url:
            referer = None
        elif "eporner.com" in v_url or (ref_url and "eporner.com" in ref_url):
            referer = ref_url if (ref_url and "eporner.com" in ref_url) else "https://www.eporner.com/"
        elif "xvideos." in v_url:
            referer = f"https://{domain}/"
        elif "erome.com" in v_url:
            referer = "https://www.erome.com/"
        elif "camwhores" in v_url:
            referer = ref_url if (ref_url and "camwhores.tv/videos/" in ref_url) else "https://www.camwhores.tv/"
        elif "bunkr" in v_url or "scdn.st" in v_url or any(
            x in (v_url or "").lower()
            for x in ("media-files", "stream-files", "milkshake", "cdn.", "bunkr.")
        ):
            ref = ref_url or ""
            if ref and ("bunkr" in ref.lower() or "/f/" in ref or "/v/" in ref):
                referer = ref if ref.endswith("/") else ref + "/"
            else:
                parsed_b = urllib.parse.urlparse(v_url)
                referer = f"{parsed_b.scheme}://{parsed_b.netloc}/"
        elif "filester." in (v_url or "").lower() or ("filester." in (ref_url or "").lower()):
            filester_ref = ref_url or ""
            if "filester." in filester_ref.lower():
                referer = filester_ref
            else:
                parsed_f = urllib.parse.urlparse(v_url)
                referer = f"{parsed_f.scheme}://{parsed_f.netloc}/"
            if referer:
                p = urllib.parse.urlparse(referer)
                origin = f"{p.scheme}://{p.netloc}"
        elif "mydaddy.cc" in v_url:
            referer = "https://hqporner.com/"
        elif any(x in (v_url or "").lower() for x in ("archivebate.com", "mxcontent.net", "mixdrop.", "m1xdrop.")) or (
            ref_url and "archivebate.com" in (ref_url or "").lower()
        ):
            # Archivebate/Mixdrop CDN links often require Archivebate referer context.
            if ref_url and "archivebate.com" in ref_url.lower():
                referer = ref_url if ref_url.endswith("/") else ref_url + "/"
            else:
                referer = "https://archivebate.com/"
            p = urllib.parse.urlparse(referer)
            origin = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else None
        elif any(x in (v_url or "").lower() for x in ("rec-ur-bate.com", "recurbate.com")):
            # Recurbate streams are safest with the watch page or site root as Referer.
            if ref_url and any(x in ref_url.lower() for x in ("rec-ur-bate.com", "recurbate.com")):
                referer = ref_url if ref_url.endswith("/") else ref_url + "/"
            else:
                referer = "https://rec-ur-bate.com/"
            p = urllib.parse.urlparse(referer)
            origin = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else None

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': referer,
            'Origin': origin,
            'Accept': '*/*',
            'Connection': 'keep-alive'
        }
        if range_header:
            headers['Range'] = range_header
        return {k: v for k, v in headers.items() if v is not None}

    # --- WEBSHARE FIX: Only for DB videos ---
    if v and ((target_url and target_url.startswith("webshare:")) or (target_url and "wsfiles.cz" in target_url)):
        async def resolve_webshare_upfront():
             try:
                 from extractors.webshare import WebshareAPI
                 ws = WebshareAPI()
                 ident = None
                 src = v_source_url or target_url
                 if src and "webshare:" in src:
                     ident = src.split(":", 2)[1]
                 elif src and "/file/" in src:
                     part = src.split('/file/')[1]
                     ident = part.split('/')[0] if '/' in part else part
                 
                 if not ident and 'wsfiles.cz' in (target_url or ""):
                     import re
                     match = re.search(r'/([a-zA-Z0-9]{10})/', target_url)
                     if match: ident = match.group(1)
                 
                 if ident:
                     logging.info(f"Resolving fresh Webshare link for {ident}...")
                     new_link = await asyncio.to_thread(ws.get_vip_link, ident)
                     return new_link
                 return None
             except Exception as e:
                 logging.error(f"Failed to resolve Webshare link upfront: {e}")
                 return None

        fresh_url = await resolve_webshare_upfront()
        if fresh_url:
            target_url = fresh_url
            try:
                v.url = fresh_url
                db.commit()
            except: pass
        elif target_url.startswith("webshare:"):
             raise HTTPException(502, detail="Could not resolve Webshare VIP link")

    try:
        if not target_url.startswith(('http://', 'https://')):
             logging.error(f"Proxy attempt with non-HTTP URL: {target_url}")
             raise HTTPException(500, detail=f"Invalid protocol for proxy: {target_url}")

        # Musí byť pred prvým použitím (cookies nižšie), inak UnboundLocalError → 500 na každom streame
        _combined_lower = f"{target_url or ''} {v_source_url or ''}".lower()
        is_unreliable = any(
            d in _combined_lower
            for d in [
                "vk.com", "vk.video", "vkvideo.ru", "okcdn.ru", "userapi.com",
                "vkvideo.net", "mycdn.me", "vk-cdn.net", "vkay.net", "vk.ru",
                "vkvideo.com", "ok.ru",
                "filester.gg", "filester.me", "cache1.filester.gg",
                "xvideos.com", "xvideos.red", "xv-video.com",
                "bunkr.cr", "bunkr.is", "bunkr.si", "bunkr.black", "bunkr.pk",
                "camwhores.tv", "cwvids.com",
                "leakporner.com", "luluvids.com", "luluvids.top",
                "archivebate.com", "mxcontent.net", "mixdrop.", "m1xdrop.",
                "rec-ur-bate.com", "recurbate.com",
            ]
        )
        # Keep VK-specific logic strictly for VK/OK domains only.
        is_vk = any(
            d in _combined_lower
            for d in [
                "vk.com", "vk.video", "vkvideo.ru", "okcdn.ru", "userapi.com",
                "vkvideo.net", "mycdn.me", "vk-cdn.net", "vkay.net", "vk.ru",
                "vkvideo.com", "ok.ru",
            ]
        )

        current_headers = await get_request_params(target_url, v_source_url)
        
        # Load cookies for VK/OK if available
        cookies = {}
        if is_vk:
            for cf in ['vk.netscape.txt', 'cookies.netscape.txt']:
                if os.path.exists(cf):
                    try:
                        with open(cf, 'r') as f:
                            for line in f:
                                if not line.startswith('#') and line.strip():
                                    parts = line.strip().split('\t')
                                    if len(parts) >= 7:
                                        cookies[parts[5]] = parts[6]
                        break
                    except: pass
        
        is_expired = False
        content_len = 0
        try:
            upstream_response = await http_session.get(target_url, headers=current_headers, cookies=cookies if cookies else None, allow_redirects=True, ssl=False)
            status_code = upstream_response.status
            content_len = int(upstream_response.headers.get('Content-Length', 0))
        except aiohttp.ClientError as e:
            logging.warning(f"Connection error proxying {target_url}: {e} - treating as expired.")
            is_expired = True
            status_code = 502
            upstream_response = None
        
        content_type = ""
        if upstream_response is not None:
            content_type = (upstream_response.headers.get("Content-Type") or "").lower()
            if not is_expired:
                is_expired = upstream_response.status in [403, 410, 401, 404]
            if 'na.mp4' in str(upstream_response.url) or (upstream_response.status == 200 and content_len < 100000):
                is_expired = True

            # Eporner-specific expiration detection: 
            if (
                upstream_response.status == 200 
                and "eporner.com" in target_url 
                and (content_len == 5433 or content_type.startswith("text/html"))
            ):
                is_expired = True

            # Filester /d/<id> page URL or cache CDN can return HTML (200) instead of media URL.
            # Force smart refresh to resolve a direct stream.
            if "filester." in (target_url or "").lower() and (
                "/d/" in (target_url or "").lower()
                or "text/html" in content_type
                or content_len < 100000
            ):
                is_expired = True

            # XVideos/XVideos.red: if target_url is a watch page (not a stream), force refresh
            if any(x in (target_url or "").lower() for x in ["xvideos.com/video", "xvideos.red/video"]) and (
                "text/html" in content_type or not any(target_url.lower().endswith(e) for e in [".mp4", ".m3u8", ".webm", ".flv"])
            ):
                is_expired = True

            # VK/OK: ak je target_url ešte stránka videa, nie priamy súbor — treba refresh (is_vk už nastavené vyššie)
            if is_vk and "/video" in target_url and not ('.mp4' in target_url.lower() or '.m3u8' in target_url.lower()):
                is_expired = True
            
            # VK stream URL validation: Check if it's a valid stream or needs refresh
            if is_vk and not is_expired:
                # Check for content-length mismatch or other VK-specific issues
                if upstream_response.status == 200:
                    # If content-length is suspiciously small or missing, refresh
                    if content_len < 100000 or content_len == 0:
                        logging.warning(f"VK stream URL has suspicious content-length: {content_len}. Refreshing...")
                        is_expired = True

        _src_for_refresh = (v.source_url if v else None) or v_source_url
        if is_expired and (_src_for_refresh or is_vk):
            logging.info(f"[PROXY][{cw_corr}] Link for video {video_id} appears expired ({upstream_response.status}). Refreshing...")
            
            # For VK videos without source_url, try to use the current URL as source
            if v and is_vk and not v.source_url:
                logging.warning(f"VK video {video_id} missing source_url, using current URL")
                v.source_url = target_url
                db.commit()
            
            async def try_refresh():
                nonlocal upstream_response, current_headers, status_code, target_url
                if not v:
                    return False

                # 0. Camwhores quick ladder: refresh rnd and retry direct before heavier re-resolve.
                if "camwhores.tv/get_file" in (target_url or "").lower():
                    try:
                        from .extractors.camwhores import normalize_camwhores_get_file_rnd

                        retry_url = normalize_camwhores_get_file_rnd(target_url)
                        logging.info("[CW-L0][%s] rnd retry_url=%s", cw_corr, retry_url[:120])
                        retry_headers = await get_request_params(retry_url, v.source_url)
                        retry_resp = await http_session.get(retry_url, headers=retry_headers, allow_redirects=True, ssl=False)
                        retry_len = int(retry_resp.headers.get("Content-Length", "0") or 0)
                        retry_ctype = (retry_resp.headers.get("Content-Type") or "").lower()
                        logging.info("[CW-L0][%s] rnd-retry: status=%s ctype=%s len=%s", cw_corr, retry_resp.status, retry_ctype, retry_len)
                        if retry_resp.status in (200, 206) and (
                            retry_resp.status == 206 or retry_len >= 65536 or "video/" in retry_ctype
                        ):
                            upstream_response.close()
                            upstream_response = retry_resp
                            current_headers = retry_headers
                            status_code = retry_resp.status
                            target_url = retry_url
                            v.url = retry_url
                            db.commit()
                            logging.info("[CW-L0][%s] quick refresh succeeded, v.url committed", cw_corr)
                            return True
                        retry_resp.close()
                        logging.info("[CW-L0][%s] rnd-retry rejected — falling to deep refresh", cw_corr)
                    except Exception as e:
                        logging.warning("[CW-L0][%s] quick refresh exception: %s", cw_corr, e)

                # 1. Webshare Refresh
                if 'webshare.cz' in (v.source_url or "") or 'wsfiles.cz' in (v.source_url or "") or (v.url and "wsfiles.cz" in v.url):
                    try:
                        from extractors.webshare import WebshareAPI
                        ws = WebshareAPI()
                        ident = None
                        src = v.source_url or v.url
                        if src and "webshare:" in src:
                            ident = src.split(":", 2)[1]
                        elif src and "/file/" in src:
                            part = src.split('/file/')[1]
                            ident = part.split('/')[0] if '/' in part else part
                        
                        if not ident and 'wsfiles.cz' in (src or ""):
                            import re
                            match = re.search(r'/([a-zA-Z0-9]{10})/', src)
                            if match: ident = match.group(1)

                        if ident:
                            new_link = await asyncio.to_thread(ws.get_vip_link, ident)
                            if new_link:
                                upstream_response.close()
                                v.url = new_link
                                db.commit()
                                current_headers = await get_request_params(v.url, v.source_url)
                                upstream_response = await http_session.get(v.url, headers=current_headers, allow_redirects=True)
                                status_code = upstream_response.status
                                return True
                    except Exception as e:
                        logging.error(f"Webshare proxy refresh failed: {e}")
                    return False

                # 2. General/VK/Deep Refresh
                async def refresh_link_smart():
                    is_camwhores_source = bool(v.source_url and "camwhores.tv" in v.source_url.lower())
                    refresh_source_url = v.source_url or v.url
                    # Backward-compat for already imported Filester rows with source_url=/f/... .
                    if (
                        "filester." in (refresh_source_url or "").lower()
                        and "/f/" in (refresh_source_url or "").lower()
                        and "filester." in (v.url or "").lower()
                        and "/d/" in (v.url or "").lower()
                    ):
                        refresh_source_url = v.url

                    # --- Camwhores: use the same extractor as import/processing ---
                    if is_camwhores_source:
                        try:
                            from .extractors.camwhores import CamwhoresExtractor

                            logging.info("[CW-L2][%s] extractor refresh: %s", cw_corr, v.source_url)
                            _cw_extractor = CamwhoresExtractor()
                            _cw_result = await _cw_extractor.extract(v.source_url)
                            if _cw_result and _cw_result.get("stream_url"):
                                _resolved = _cw_result["stream_url"]
                                logging.info(
                                    "[CW-L2][%s] extractor(%s)→url=%s",
                                    cw_corr,
                                    _cw_result.get("_resolver") or "unknown",
                                    _resolved[:120],
                                )
                                return {
                                    "url": _resolved,
                                    "height": _cw_result.get("height") or 0,
                                    "_prevalidated": bool(_cw_result.get("_prevalidated")),
                                }
                            logging.warning("[CW-L2][%s] extractor returned no stream", cw_corr)
                        except Exception as _e:
                            logging.warning("[CW-L2][%s] extractor refresh error: %s", cw_corr, _e)
                        return None

                    # Try Plugin First (Eporner, Bunkr, Filester, XVideos, etc.) - FAST
                    try:
                        from .extractors.registry import ExtractorRegistry
                        from .extractors import init_registry, register_extended_extractors
                        # Ensure ALL extractors (including XVideos, Filester, etc.) are registered
                        init_registry()
                        register_extended_extractors()
                        plugin = ExtractorRegistry.find_extractor(refresh_source_url)
                        if plugin:
                             logging.info(f"[REFRESH] Using plugin {plugin.name} for refresh of video {v.id}")
                             res = await plugin.extract(refresh_source_url)
                             if res and res.get('stream_url'):
                                 return {'url': res['stream_url'], 'height': res.get('height')}
                             logging.warning(f"[REFRESH] Plugin {plugin.name} found no stream for {refresh_source_url}")
                    except Exception as e:
                         logging.warning(f"Plugin smart refresh failed: {e}")

                    # Fallback to yt-dlp for other deep sites (VK, xvideos, etc.)
                    def run_ytdlp():
                        is_deep = any(
                            x in (refresh_source_url or "")
                            for x in [
                                'xvideos.com', 'xvideos.red', 'xv-video.com',
                                'xhamster.com',
                                'eporner.com',
                                'spankbang.com',
                                'vk.com', 'vk.video', 'vkvideo.ru',
                                'pornhub.com',
                            ]
                        )
                        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                        opts = {
                            'quiet': True, 'skip_download': True,
                            'format': 'bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best',
                            'extract_flat': False,
                            'socket_timeout': 20,
                            'user_agent': user_agent,
                            'http_headers': {'User-Agent': user_agent, 'Referer': refresh_source_url}
                        }
                        for cf in ['xvideos.netscape.txt', 'vk.netscape.txt', 'eporner.netscape.txt', 'cookies.netscape.txt']:
                            if os.path.exists(cf):
                                opts['cookiefile'] = cf
                                break
                        info = None
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(refresh_source_url, download=False)
                        if not info:
                            return None
                        # Pick best video URL from formats list
                        best_url = info.get('url')
                        best_height = info.get('height') or 0
                        formats = info.get('formats', [])
                        if formats:
                            best_score = -1
                            for f in formats:
                                furl = f.get('url')
                                if not furl: continue
                                h = f.get('height') or 0
                                score = h * 10
                                if f.get('ext') == 'mp4': score += 5
                                if score > best_score:
                                    best_score = score
                                    best_url = furl
                                    best_height = h
                        return {'url': best_url, 'height': best_height}

                    return await asyncio.to_thread(run_ytdlp)

                try:
                    info = await refresh_link_smart()
                    if not info:
                        logging.warning("[CW-L2][%s] refresh_link_smart returned None", cw_corr)
                        return False

                    new_url = info.get('url')
                    # VK specific: might be in formats list
                    if not new_url and 'formats' in info:
                        max_h = 0
                        for f in info['formats']:
                            if f.get('url') and (f.get('height') or 0) >= max_h:
                                max_h = f.get('height') or 0
                                new_url = f['url']

                    logging.info("[CW-L2][%s] new_url resolved: %s", cw_corr, (new_url or "None")[:120])

                    if new_url:
                        upstream_response.close()
                        prevalidated = info.get("_prevalidated", False)

                        if prevalidated:
                            # CamwhoresExtractor already probed the URL internally.
                            # Skip re-probe — make ONE real request with the client's original
                            # Range header so the streamed response is correct.
                            logging.info("[CW-L2][%s] pre-validated → streaming directly (no re-probe)", cw_corr)
                            current_headers = await get_request_params(new_url, v.source_url)
                            upstream_response = await http_session.get(
                                new_url, headers=current_headers, allow_redirects=True, ssl=False
                            )
                            stream_ctype = (upstream_response.headers.get("Content-Type") or "").lower()
                            logging.info(
                                "[CW-L2][%s] stream-start: status=%s ctype=%s",
                                cw_corr, upstream_response.status, stream_ctype,
                            )
                            if upstream_response.status in (200, 206):
                                v.url = new_url
                                target_url = new_url
                                if info.get('height'):
                                    v.height = info['height']
                                db.commit()
                                status_code = upstream_response.status
                                logging.info("[CW-L2][%s] v.url committed → %s", cw_corr, new_url[:120])
                                # Backfill height/duration via ffprobe if still missing
                                if (not v.height or not v.duration) and v.source_url:
                                    _ffprobe_vid_id = v.id
                                    _ffprobe_url = new_url
                                    _ffprobe_ref = v.source_url
                                    async def _cw_bg_ffprobe():
                                        try:
                                            _proc = VIPVideoProcessor()
                                            _ff = await asyncio.to_thread(
                                                _proc._ffprobe_fallback,
                                                _ffprobe_url,
                                                {},
                                                _ffprobe_ref,
                                            )
                                            if _ff.get('height') or _ff.get('duration'):
                                                _bdb = SessionLocal()
                                                try:
                                                    _bv = _bdb.query(Video).get(_ffprobe_vid_id)
                                                    if _bv:
                                                        if _ff.get('height') and not _bv.height:
                                                            _bv.height = int(_ff['height'])
                                                        if _ff.get('width') and not _bv.width:
                                                            _bv.width = int(_ff['width'])
                                                        if _ff.get('duration') and not _bv.duration:
                                                            _bv.duration = float(_ff['duration'])
                                                        _bdb.commit()
                                                        logging.info(
                                                            "[CW-L2][%s] bg-ffprobe filled: h=%s dur=%s",
                                                            cw_corr, _ff.get('height'), _ff.get('duration')
                                                        )
                                                finally:
                                                    _bdb.close()
                                        except Exception as _fe:
                                            logging.warning("[CW-L2][%s] bg-ffprobe error: %s", cw_corr, _fe)
                                    asyncio.create_task(_cw_bg_ffprobe())
                                return True
                            upstream_response.close()
                            logging.warning(
                                "[CW-L2][%s] stream-start rejected: status=%s url=%s",
                                cw_corr, upstream_response.status, new_url[:120],
                            )
                        else:
                            # Standard candidate probe for non-extractor sources (VK, yt-dlp, etc.)
                            candidate_headers = await get_request_params(new_url, v.source_url)
                            candidate_resp = await http_session.get(
                                new_url, headers=candidate_headers, allow_redirects=True, ssl=False
                            )
                            candidate_len = int(candidate_resp.headers.get("Content-Length", "0") or 0)
                            candidate_ctype = (candidate_resp.headers.get("Content-Type") or "").lower()
                            logging.info(
                                "[CW-L2][%s] candidate probe → status=%s ctype=%s len=%s",
                                cw_corr, candidate_resp.status, candidate_ctype, candidate_len,
                            )
                            probe_ok = candidate_resp.status in (200, 206) and (
                                candidate_resp.status == 206
                                or candidate_len >= 65536
                                or "video/" in candidate_ctype
                            )
                            if probe_ok:
                                v.url = new_url
                                target_url = new_url
                                if info.get('height'):
                                    v.height = info['height']
                                db.commit()
                                current_headers = candidate_headers
                                upstream_response = candidate_resp
                                status_code = upstream_response.status
                                logging.info("[CW-L2][%s] v.url committed → %s", cw_corr, new_url[:120])
                                return True
                            candidate_resp.close()
                            logging.warning(
                                "[CW-L2][%s] candidate rejected: status=%s ctype=%s len=%s url=%s",
                                cw_corr,
                                getattr(candidate_resp, 'status', '?'),
                                candidate_ctype,
                                candidate_len,
                                new_url[:120],
                            )
                except Exception as e:
                    logging.error("[CW-L2][%s] refresh raised: %s", cw_corr, e, exc_info=True)
                return False

            refresh_success = await try_refresh()
            if not refresh_success and is_vk:
                upstream_response.close()
                raise HTTPException(500, detail="Failed to refresh VK stream. Check if cookies are needed.")
            if not refresh_success and v and v.source_url and "bunkr" in (v.source_url or "").lower():
                upstream_response.close()
                raise HTTPException(502, detail="Bunkr stream expired and re-resolve failed. Try Regenerate or check bunkr.cookies.txt.")
            if (
                not refresh_success
                and v
                and v.source_url
                and "camwhores.tv" in (v.source_url or "").lower()
                and "/videos/" in (v.source_url or "")
            ):
                upstream_response.close()
                raise HTTPException(
                    502,
                    detail="cw_refresh_failed: Camwhores stream unavailable. Open the watch page while logged in and ensure browser automation can load it, then Regenerate.",
                )
            if (
                not refresh_success
                and v
                and "camwhores.tv/get_file" in str(v.url or "").lower()
                and "camwhores.tv/videos/" not in str(v.source_url or "").lower()
            ):
                upstream_response.close()
                raise HTTPException(
                    502,
                    detail="cw_source_missing: Camwhores video has no watch-page source_url for re-resolve.",
                )

        if upstream_response.status >= 400:
            error_text = await upstream_response.text()
            logging.error(f"Upstream error ({upstream_response.status}) for video {v.id if v else video_id}: {error_text[:200]}")
            upstream_response.close()
            if "camwhores.tv/get_file" in (target_url or "").lower():
                raise HTTPException(status_code=502, detail=f"cw_upstream_5xx: Camwhores upstream returned {upstream_response.status}")
            raise HTTPException(status_code=upstream_response.status, detail="Upstream link unavailable")

        # --- STREAMING RESPONSE ---
        # 1. Clean up headers. Remove specific ones that can cause proxy loops or mismatch
        excluded_headers = {
            'content-encoding', 'content-length', 'transfer-encoding', 
            'connection', 'keep-alive', 'host', 'server', 'vary',
            'x-frame-options', 'content-security-policy', 'strict-transport-security',
            'x-content-type-options', 'access-control-allow-origin', 'access-control-allow-methods',
            'content-disposition'  # Exclude to prevent Unicode encoding errors (e.g., emojis in filenames)
        }
        response_headers = {k: v for k, v in upstream_response.headers.items() if k.lower() not in excluded_headers}
        
        # 2. Handle Status and Range Headers carefully
        status_code = upstream_response.status

        # Backfill height/duration via bg ffprobe for CW videos that streamed OK but lack metadata
        if (
            v is not None
            and status_code in (200, 206)
            and v.source_url and "camwhores.tv/videos/" in v.source_url
            and (not v.height or not v.duration)
            and "get_file" in (v.url or "")
        ):
            _bfp_vid_id = v.id
            _bfp_url = v.url
            _bfp_ref = v.source_url
            async def _cw_main_bg_ffprobe():
                try:
                    _proc = VIPVideoProcessor()
                    _ff = await asyncio.to_thread(_proc._ffprobe_fallback, _bfp_url, {}, _bfp_ref)
                    if _ff.get('height') or _ff.get('duration'):
                        _bdb = SessionLocal()
                        try:
                            _bv = _bdb.query(Video).get(_bfp_vid_id)
                            if _bv:
                                if _ff.get('height') and not _bv.height:
                                    _bv.height = int(_ff['height'])
                                if _ff.get('width') and not _bv.width:
                                    _bv.width = int(_ff['width'])
                                if _ff.get('duration') and not _bv.duration:
                                    _bv.duration = float(_ff['duration'])
                                _bdb.commit()
                                logging.info(
                                    "[CW-meta] bg-ffprobe filled vid=%s h=%s dur=%s",
                                    _bfp_vid_id, _ff.get('height'), _ff.get('duration')
                                )
                        finally:
                            _bdb.close()
                except Exception as _fe:
                    logging.warning("[CW-meta] bg-ffprobe error vid=%s: %s", _bfp_vid_id, _fe)
            asyncio.create_task(_cw_main_bg_ffprobe())

        # If browser sent a Range but we got 200, we must clear Content-Length or the browser
        # might try to match the range it asked for against the full file we are sending.
        # Actually, best is to pass Content-Length only if it matches exactly what we're sending.
        # For unreliable streams, skip Content-Length to avoid mismatch after refresh or upstream interruption
        if 'Content-Length' in upstream_response.headers and not is_unreliable:
            response_headers['Content-Length'] = upstream_response.headers['Content-Length']
        if 'Content-Range' in upstream_response.headers:
            response_headers['Content-Range'] = upstream_response.headers['Content-Range']

        # Force these for stability and CORS
        response_headers.update({
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
            "X-Video-ID": str(video_id),
            "Cache-Control": "no-cache, no-store, must-revalidate" # Don't cache proxy streams
        })

        async def content_streamer():
            try:
                # iter_chunked with a specific size (128KB) is often the most stable balanced choice
                async for chunk in upstream_response.content.iter_chunked(128 * 1024):
                    if chunk:
                        yield chunk
            except Exception as e:
                logging.debug(f"Stream finished or interrupted for {video_id}")
            finally:
                upstream_response.close()

        # media_type is important for the browser to know it's a video
        media_type = upstream_response.headers.get("Content-Type", "video/mp4")
        
        return StreamingResponse(
            content_streamer(), 
            status_code=status_code, 
            headers=response_headers,
            media_type=media_type
        )

    except HTTPException:
        raise
    except Exception as e:
        if 'upstream_response' in locals() and upstream_response:
            try: upstream_response.close()
            except: pass
        logging.error(f"Proxy error for video {video_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return StreamingResponse(iter_file(), headers={"Content-Disposition": content_disposition})

def get_stream_url(video_id: int):
    return f"/stream_proxy/{video_id}.mp4"

# --- UTILITY ENDPOINTS ---

@api_v1_router.get("/export-library")
@api_legacy_router.get("/export-library")
def export_library(db: Session = Depends(get_db)):
    """Export entire library as JSON"""
    videos = db.query(Video).all()
    results = []
    for v in videos:
        video_dict = v.__dict__
        video_dict.pop('_sa_instance_state', None)
        # Convert datetime to ISO format
        if video_dict.get('created_at'):
            video_dict['created_at'] = video_dict['created_at'].isoformat()
        if video_dict.get('last_checked'):
            video_dict['last_checked'] = video_dict['last_checked'].isoformat()
        results.append(video_dict)
    
    return JSONResponse(content={
        "export_date": datetime.datetime.utcnow().isoformat(),
        "total_videos": len(results),
        "videos": results
    })

@api_v1_router.post("/batch/tag")
@api_legacy_router.post("/batch/tag")
def batch_tag_videos(video_ids: List[int] = Body(...), tags: str = Body(...), db: Session = Depends(get_db)):
    """Add tags to multiple videos"""
    for vid_id in video_ids:
        video = db.query(Video).get(vid_id)
        if video:
            existing_tags = set(video.tags.split(',')) if video.tags else set()
            new_tags = set(tags.split(','))
            combined = existing_tags.union(new_tags)
            video.tags = ','.join(filter(None, combined))
    db.commit()
    return {"success": True, "updated": len(video_ids)}

@api_v1_router.post("/batch/delete")
@api_legacy_router.post("/batch/delete")
def batch_delete_videos(video_ids: List[int] = Body(...), db: Session = Depends(get_db)):
    """Delete multiple videos"""
    for vid_id in video_ids:
        video = db.query(Video).get(vid_id)
        if video:
            # Delete thumbnail files
            if video.thumbnail_path:
                thumb_path = f"app{video.thumbnail_path.split('?')[0]}"
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            db.delete(video)
    db.commit()
    return {"success": True, "deleted": len(video_ids)}

# ...napr. v get_videos alebo export_videos môžete pridať do výsledku:
# video['stream_url'] = get_stream_url(video.id)


# ===== DISCOVERY PROFILES API =====

class DiscoveryProfileCreate(BaseModel):
    name: str
    enabled: bool = True
    schedule_type: str = "interval"  # "interval", "cron", "manual"
    schedule_value: str = "3600"  # seconds for interval, cron expression for cron
    keywords: str = ""
    exclude_keywords: str = ""
    sources: List[str] = []
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    max_results: int = 20
    auto_import: bool = False
    batch_prefix: str = "Auto"

class DiscoveryProfileUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    schedule_type: Optional[str] = None
    schedule_value: Optional[str] = None
    keywords: Optional[str] = None
    exclude_keywords: Optional[str] = None
    sources: Optional[List[str]] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    max_results: Optional[int] = None
    auto_import: Optional[bool] = None
    batch_prefix: Optional[str] = None

class ProbeUrlBody(BaseModel):
    url: str

@api_v1_router.get("/discovery/search-sources")
@api_legacy_router.get("/discovery/search-sources")
async def discovery_search_sources_list():
    """Catalog of discovery search keys for dashboard UI."""
    from .source_catalog import DISCOVERY_SOURCE_OPTIONS, EXTRACT_ONLY_SOURCE_NOTES
    return {
        "discovery_sources": DISCOVERY_SOURCE_OPTIONS,
        "import_only_sources": EXTRACT_ONLY_SOURCE_NOTES,
    }

@api_v1_router.post("/tools/probe-url")
@api_legacy_router.post("/tools/probe-url")
async def tools_probe_url(body: ProbeUrlBody):
    """Try plugin extractors then yt-dlp to see if a URL is supported."""
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    from .extractors import init_registry, register_extended_extractors
    from .extractors.registry import ExtractorRegistry

    init_registry()
    register_extended_extractors()

    plugin = ExtractorRegistry.find_extractor(url)
    if plugin:
        try:
            res = await plugin.extract(url)
            if res and res.get("stream_url"):
                return {
                    "supported": True,
                    "method": "extractor",
                    "extractor": plugin.name,
                    "title": res.get("title"),
                    "has_stream": True,
                    "is_hls": bool(res.get("is_hls")),
                }
            return {
                "supported": bool(res),
                "method": "extractor",
                "extractor": plugin.name,
                "title": (res or {}).get("title"),
                "has_stream": bool(res and res.get("stream_url")),
                "is_hls": bool((res or {}).get("is_hls")),
                "error": None if (res and res.get("stream_url")) else "Extractor returned no stream_url",
            }
        except Exception as e:
            return {
                "supported": False,
                "method": "extractor",
                "extractor": plugin.name,
                "error": str(e),
            }

    def _ytdlp_probe():
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_ytdlp_probe)
        if info:
            ie = info.get("extractor") or info.get("ie_key") or "yt-dlp"
            has_stream = bool(info.get("url") or info.get("formats"))
            return {
                "supported": True,
                "method": "yt-dlp",
                "extractor": ie,
                "title": info.get("title"),
                "has_stream": has_stream,
            }
    except Exception as e:
        return {
            "supported": False,
            "method": "none",
            "extractor": None,
            "error": str(e),
        }

    return {"supported": False, "method": "none", "extractor": None}

@api_legacy_router.get("/discovery/profiles")
async def get_discovery_profiles(db: Session = Depends(get_db)):
    """Get all discovery profiles."""
    profiles = db.query(DiscoveryProfile).order_by(desc(DiscoveryProfile.created_at)).all()

    result = []
    for profile in profiles:
        profile_dict = {
            "id": profile.id,
            "name": profile.name,
            "enabled": profile.enabled,
            "schedule_type": profile.schedule_type,
            "schedule_value": profile.schedule_value,
            "keywords": profile.keywords,
            "exclude_keywords": profile.exclude_keywords,
            "sources": profile.sources or [],
            "min_height": profile.min_height,
            "max_height": profile.max_height,
            "aspect_ratio": profile.aspect_ratio,
            "min_duration": profile.min_duration,
            "max_duration": profile.max_duration,
            "max_results": profile.max_results,
            "auto_import": profile.auto_import,
            "batch_prefix": profile.batch_prefix,
            "last_run": profile.last_run.isoformat() if profile.last_run else None,
            "total_runs": profile.total_runs,
            "total_found": profile.total_found,
            "total_imported": profile.total_imported,
            "created_at": profile.created_at.isoformat(),
            "updated_at": profile.updated_at.isoformat()
        }
        result.append(profile_dict)

    return {"profiles": result}

@api_legacy_router.get("/discovery/profiles/{profile_id}")
async def get_discovery_profile(profile_id: int, db: Session = Depends(get_db)):
    """Get a specific discovery profile."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    return {
        "id": profile.id,
        "name": profile.name,
        "enabled": profile.enabled,
        "schedule_type": profile.schedule_type,
        "schedule_value": profile.schedule_value,
        "keywords": profile.keywords,
        "exclude_keywords": profile.exclude_keywords,
        "sources": profile.sources or [],
        "min_height": profile.min_height,
        "max_height": profile.max_height,
        "aspect_ratio": profile.aspect_ratio,
        "min_duration": profile.min_duration,
        "max_duration": profile.max_duration,
        "max_results": profile.max_results,
        "auto_import": profile.auto_import,
        "batch_prefix": profile.batch_prefix,
        "last_run": profile.last_run.isoformat() if profile.last_run else None,
        "total_runs": profile.total_runs,
        "total_found": profile.total_found,
        "total_imported": profile.total_imported,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat()
    }

@api_legacy_router.post("/discovery/profiles")
async def create_discovery_profile(profile_data: DiscoveryProfileCreate, db: Session = Depends(get_db)):
    """Create a new discovery profile."""
    # Check if name already exists
    existing = db.query(DiscoveryProfile).filter(DiscoveryProfile.name == profile_data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Profile name already exists")

    from .source_catalog import filter_valid_discovery_sources

    # Create profile
    profile = DiscoveryProfile(
        name=profile_data.name,
        enabled=profile_data.enabled,
        schedule_type=profile_data.schedule_type,
        schedule_value=profile_data.schedule_value,
        keywords=profile_data.keywords,
        exclude_keywords=profile_data.exclude_keywords,
        sources=filter_valid_discovery_sources(profile_data.sources),
        min_height=profile_data.min_height,
        max_height=profile_data.max_height,
        aspect_ratio=profile_data.aspect_ratio,
        min_duration=profile_data.min_duration,
        max_duration=profile_data.max_duration,
        max_results=profile_data.max_results,
        auto_import=profile_data.auto_import,
        batch_prefix=profile_data.batch_prefix
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Schedule the profile if enabled
    if profile.enabled:
        try:
            scheduler = get_scheduler()
            if profile.schedule_type == "interval":
                interval_seconds = int(profile.schedule_value)
                scheduler.add_interval_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    seconds=interval_seconds,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
            elif profile.schedule_type == "cron":
                scheduler.add_cron_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    cron_expression=profile.schedule_value,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
        except Exception as e:
            print(f"Failed to schedule new profile: {e}")

    return {"success": True, "profile_id": profile.id}

@api_legacy_router.put("/discovery/profiles/{profile_id}")
async def update_discovery_profile(profile_id: int, profile_data: DiscoveryProfileUpdate, db: Session = Depends(get_db)):
    """Update a discovery profile."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Update fields
    update_data = profile_data.dict(exclude_unset=True)
    if "sources" in update_data and update_data["sources"] is not None:
        from .source_catalog import filter_valid_discovery_sources
        update_data["sources"] = filter_valid_discovery_sources(update_data["sources"])
    for field, value in update_data.items():
        setattr(profile, field, value)

    profile.updated_at = datetime.datetime.utcnow()
    db.commit()

    # Re-schedule the profile
    try:
        scheduler = get_scheduler()
        scheduler.remove_job(f"profile_{profile.id}")

        if profile.enabled:
            if profile.schedule_type == "interval":
                interval_seconds = int(profile.schedule_value)
                scheduler.add_interval_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    seconds=interval_seconds,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
            elif profile.schedule_type == "cron":
                scheduler.add_cron_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    cron_expression=profile.schedule_value,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
    except Exception as e:
        print(f"Failed to re-schedule profile: {e}")

    return {"success": True}

@api_legacy_router.delete("/discovery/profiles/{profile_id}")
async def delete_discovery_profile(profile_id: int, db: Session = Depends(get_db)):
    """Delete a discovery profile."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Remove from scheduler
    try:
        scheduler = get_scheduler()
        scheduler.remove_job(f"profile_{profile.id}")
    except Exception as e:
        print(f"Failed to remove job from scheduler: {e}")

    # Delete notifications
    db.query(DiscoveryNotification).filter(DiscoveryNotification.profile_id == profile_id).delete()

    # Delete profile
    db.delete(profile)
    db.commit()

    return {"success": True}

@api_legacy_router.post("/discovery/profiles/{profile_id}/run")
async def run_profile_now(profile_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually trigger a discovery profile to run now."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Run in background
    background_tasks.add_task(run_discovery_profile, profile_id)

    return {"success": True, "message": f"Profile '{profile.name}' queued to run"}

@api_legacy_router.post("/discovery/profiles/{profile_id}/toggle")
async def toggle_profile(profile_id: int, db: Session = Depends(get_db)):
    """Enable or disable a discovery profile."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile.enabled = not profile.enabled
    profile.updated_at = datetime.datetime.utcnow()
    db.commit()

    # Update scheduler
    try:
        scheduler = get_scheduler()
        if profile.enabled:
            if profile.schedule_type == "interval":
                interval_seconds = int(profile.schedule_value)
                scheduler.add_interval_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    seconds=interval_seconds,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
            elif profile.schedule_type == "cron":
                scheduler.add_cron_job(
                    run_discovery_profile,
                    job_id=f"profile_{profile.id}",
                    cron_expression=profile.schedule_value,
                    description=f"Discovery: {profile.name}",
                    args=(profile.id,)
                )
        else:
            scheduler.remove_job(f"profile_{profile.id}")
    except Exception as e:
        print(f"Failed to update scheduler: {e}")

    return {"success": True, "enabled": profile.enabled}

@api_legacy_router.get("/discovery/notifications")
async def get_notifications(unread_only: bool = False, limit: int = 50, db: Session = Depends(get_db)):
    """Get discovery notifications."""
    query = db.query(DiscoveryNotification)

    if unread_only:
        query = query.filter(DiscoveryNotification.read == False)

    notifications = query.order_by(desc(DiscoveryNotification.created_at)).limit(limit).all()

    result = []
    for notif in notifications:
        result.append({
            "id": notif.id,
            "profile_id": notif.profile_id,
            "profile_name": notif.profile_name,
            "type": notif.notification_type,
            "message": notif.message,
            "video_count": notif.video_count,
            "read": notif.read,
            "created_at": notif.created_at.isoformat()
        })

    return {"notifications": result}

@api_legacy_router.post("/discovery/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, db: Session = Depends(get_db)):
    """Mark a notification as read."""
    notif = db.query(DiscoveryNotification).filter(DiscoveryNotification.id == notification_id).first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.read = True
    db.commit()

    return {"success": True}

@api_legacy_router.post("/discovery/notifications/mark-all-read")
async def mark_all_notifications_read(db: Session = Depends(get_db)):
    """Mark all notifications as read."""
    db.query(DiscoveryNotification).update({"read": True})
    db.commit()

    return {"success": True}

@api_legacy_router.get("/scheduler/jobs")
async def get_scheduler_jobs():
    """Get all scheduled jobs."""
    try:
        scheduler = get_scheduler()
        jobs = scheduler.get_jobs()

        result = []
        for job_id, metadata in jobs.items():
            result.append({
                "job_id": job_id,
                **metadata,
                "next_run": metadata.get('next_run').isoformat() if metadata.get('next_run') else None,
                "last_run": metadata.get('last_run').isoformat() if metadata.get('last_run') else None,
                "added_at": metadata.get('added_at').isoformat() if metadata.get('added_at') else None
            })

        return {"jobs": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== DISCOVERED VIDEOS (REVIEW) API =====

@api_legacy_router.get("/discovery/review/{profile_id}")
async def get_discovered_videos(profile_id: int, imported: bool = False, db: Session = Depends(get_db)):
    """Get discovered videos for a profile for review."""
    query = db.query(DiscoveredVideo).filter(DiscoveredVideo.profile_id == profile_id)

    if not imported:
        query = query.filter(DiscoveredVideo.imported == False)

    discovered = query.order_by(desc(DiscoveredVideo.discovered_at)).all()

    result = []
    for vid in discovered:
        result.append({
            "id": vid.id,
            "profile_id": vid.profile_id,
            "profile_name": vid.profile_name,
            "title": vid.title,
            "url": vid.url,
            "source_url": vid.source_url,
            "thumbnail": vid.thumbnail,
            "duration": vid.duration,
            "width": vid.width,
            "height": vid.height,
            "source": vid.source,
            "imported": vid.imported,
            "video_id": vid.video_id,
            "discovered_at": vid.discovered_at.isoformat(),
            "imported_at": vid.imported_at.isoformat() if vid.imported_at else None
        })

    return {"discovered_videos": result}

@api_legacy_router.post("/discovery/import-selected")
async def import_selected_videos(
    video_ids: List[int] = Body(...),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    """Import selected discovered videos to main library."""
    imported_count = 0

    for vid_id in video_ids:
        discovered = db.query(DiscoveredVideo).filter(DiscoveredVideo.id == vid_id).first()

        if not discovered or discovered.imported:
            continue

        # Check if URL already exists in main videos
        existing = db.query(Video).filter(Video.url == discovered.url).first()
        if existing:
            # Mark as imported with existing video_id
            discovered.imported = True
            discovered.video_id = existing.id
            discovered.imported_at = datetime.datetime.utcnow()
            continue

        # Create new video entry
        video = Video(
            title=discovered.title,
            url=discovered.url,
            source_url=discovered.source_url,
            thumbnail_path=discovered.thumbnail,
            duration=discovered.duration,
            width=discovered.width,
            height=discovered.height,
            batch_name=f"{discovered.profile_name}-{datetime.datetime.utcnow().strftime('%Y%m%d')}",
            storage_type='remote',
            status='pending'
        )

        db.add(video)
        db.flush()

        # Mark discovered video as imported
        discovered.imported = True
        discovered.video_id = video.id
        discovered.imported_at = datetime.datetime.utcnow()

        # Queue for processing in background
        from app.workers.tasks import process_video_task
        process_video_task.delay(video.id)

        imported_count += 1

    db.commit()

    return {"success": True, "imported_count": imported_count}

@api_legacy_router.delete("/discovery/review/{discovered_id}")
async def delete_discovered_video(discovered_id: int, db: Session = Depends(get_db)):
    """Delete a discovered video from review list."""
    discovered = db.query(DiscoveredVideo).filter(DiscoveredVideo.id == discovered_id).first()

    if not discovered:
        raise HTTPException(status_code=404, detail="Discovered video not found")

    db.delete(discovered)
    db.commit()

    return {"success": True}

@api_legacy_router.post("/discovery/clear-imported/{profile_id}")
async def clear_imported_discoveries(profile_id: int, db: Session = Depends(get_db)):
    """Clear all imported discovered videos for a profile."""
    deleted_count = db.query(DiscoveredVideo).filter(
        DiscoveredVideo.profile_id == profile_id,
        DiscoveredVideo.imported == True
    ).delete()

    db.commit()

    return {"success": True, "deleted_count": deleted_count}


# ============================================
# QUANTUM UX BACKEND API ENDPOINTS
# Supporting 10 powerful UX features
# ============================================

# ========== TAG CLOUD & AUTOCOMPLETE ==========
@api_v1_router.get("/tags/cloud")
@api_legacy_router.get("/tags/cloud")
async def get_tag_cloud(db: Session = Depends(get_db)):
    """Get tag cloud with frequency counts."""
    from sqlalchemy import func

    # Get all tags and count their frequency
    all_tags = db.query(Video.tags, Video.ai_tags).filter(
        or_(Video.tags != "", Video.ai_tags != "")
    ).all()

    tag_counts = {}
    for tags, ai_tags in all_tags:
        for tag_str in [tags, ai_tags]:
            if tag_str:
                for tag in tag_str.split(','):
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Convert to sorted list
    tag_list = [{"tag": tag, "count": count} for tag, count in tag_counts.items()]
    tag_list.sort(key=lambda x: x['count'], reverse=True)

    return {"tags": tag_list[:50]}  # Top 50 tags

@api_v1_router.get("/tags/search")
@api_legacy_router.get("/tags/search")
async def search_tags(q: str, db: Session = Depends(get_db)):
    """Search for tags matching query."""
    all_tags = db.query(Video.tags, Video.ai_tags).filter(
        or_(Video.tags.contains(q), Video.ai_tags.contains(q))
    ).limit(100).all()

    matching_tags = set()
    for tags, ai_tags in all_tags:
        for tag_str in [tags, ai_tags]:
            if tag_str:
                for tag in tag_str.split(','):
                    tag = tag.strip()
                    if tag and q.lower() in tag.lower():
                        matching_tags.add(tag)

    tag_list = [{"tag": tag} for tag in sorted(matching_tags)]
    return {"tags": tag_list[:20]}


# ========== LINK HEALTH DASHBOARD ==========
@api_v1_router.get("/health/stats")
@api_legacy_router.get("/health/stats")
async def get_health_stats(db: Session = Depends(get_db)):
    """Get overall library health statistics."""
    total = db.query(Video).count()
    working = db.query(Video).filter(Video.link_status == 'working').count()
    broken = db.query(Video).filter(Video.link_status == 'broken').count()
    unknown = db.query(Video).filter(Video.link_status == 'unknown').count()
    never_checked = db.query(Video).filter(Video.last_checked == None).count()

    health_percentage = (working / total * 100) if total > 0 else 0

    return {
        "total": total,
        "working": working,
        "broken": broken,
        "unknown": unknown,
        "never_checked": never_checked,
        "health_percentage": round(health_percentage, 1)
    }

@api_v1_router.get("/health/sources")
@api_legacy_router.get("/health/sources")
async def get_health_by_source(db: Session = Depends(get_db)):
    """Get health statistics grouped by source plus Unknown domain backlog."""
    from collections import Counter

    from .source_catalog import classify_library_source_name, unknown_domain_from_urls

    videos = db.query(Video).all()

    sources = {}
    domain_counts: Counter = Counter()

    for video in videos:
        label = classify_library_source_name(video.url, video.source_url)
        if label == "Unknown":
            host = unknown_domain_from_urls(video.url, video.source_url)
            if host:
                domain_counts[host] += 1

        if label not in sources:
            sources[label] = {"total": 0, "working": 0, "broken": 0, "unknown": 0}

        sources[label]["total"] += 1
        status = video.link_status or 'unknown'
        sources[label][status] = sources[label].get(status, 0) + 1

    source_list = []
    for name, stats in sources.items():
        score = (stats['working'] / stats['total'] * 100) if stats['total'] > 0 else 0
        source_list.append({
            "name": name,
            "score": round(score, 1),
            "stats": stats
        })

    source_list.sort(key=lambda x: x['score'], reverse=True)

    unknown_domains = [
        {"host": host, "count": count}
        for host, count in domain_counts.most_common(50)
    ]

    return {"sources": source_list, "unknown_domains": unknown_domains}

@api_v1_router.post("/health/refresh-broken")
@api_legacy_router.post("/health/refresh-broken")
async def refresh_broken_links(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Refresh all broken links in the background."""
    broken_videos = db.query(Video).filter(Video.link_status == 'broken').all()

    async def refresh_all():
        for video in broken_videos:
            try:
                # Use existing refresh logic from services
                pass  # TODO: Call refresh_video_link
            except Exception as e:
                print(f"Failed to refresh {video.id}: {e}")

    background_tasks.add_task(refresh_all)

    return {"status": "started", "count": len(broken_videos)}


# ========== DISCOVERY DASHBOARD ENHANCEMENTS ==========
@api_legacy_router.get("/discovery/profiles/{profile_id}/stats")
async def get_discovery_profile_stats(profile_id: int, db: Session = Depends(get_db)):
    """Get statistics for a specific discovery profile."""
    profile = db.query(DiscoveryProfile).filter(DiscoveryProfile.id == profile_id).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Get match counts
    total_found = db.query(DiscoveredVideo).filter(DiscoveredVideo.profile_id == profile_id).count()
    imported = db.query(DiscoveredVideo).filter(
        DiscoveredVideo.profile_id == profile_id,
        DiscoveredVideo.imported == True
    ).count()
    pending = total_found - imported

    # Calculate progress
    progress = (imported / total_found * 100) if total_found > 0 else 0

    return {
        "profile_id": profile_id,
        "total_found": total_found,
        "imported": imported,
        "pending": pending,
        "progress": round(progress, 1),
        "last_run": profile.last_run.isoformat() if profile.last_run else None,
        "status": "running" if False else "idle"  # TODO: Check actual running status
    }

@api_legacy_router.post("/discovery/profiles/{profile_id}/run")
async def run_discovery_profile_endpoint(profile_id: int, background_tasks: BackgroundTasks):
    """Manually trigger a discovery profile run."""
    background_tasks.add_task(run_discovery_profile, profile_id)
    return {"status": "started"}

@api_legacy_router.get("/discovery/profiles/{profile_id}/matches")
async def get_discovery_matches(profile_id: int, db: Session = Depends(get_db)):
    """Get pending matches for a discovery profile."""
    matches = db.query(DiscoveredVideo).filter(
        DiscoveredVideo.profile_id == profile_id,
        DiscoveredVideo.imported == False
    ).order_by(DiscoveredVideo.discovered_at.desc()).limit(50).all()

    return {"matches": [
        {
            "id": m.id,
            "title": m.title,
            "url": m.url,
            "thumbnail": m.thumbnail,
            "duration": m.duration,
            "width": m.width,
            "height": m.height,
            "source": m.source,
            "discovered_at": m.discovered_at.isoformat()
        }
        for m in matches
    ]}


# ========== SESSION & PROGRESS TRACKING ==========
class VideoProgressUpdate(BaseModel):
    video_id: int
    current_time: float
    duration: float

@api_v1_router.post("/session/progress")
@api_legacy_router.post("/session/progress")
async def update_video_progress(progress: VideoProgressUpdate, db: Session = Depends(get_db)):
    """Update video playback progress."""
    video = db.query(Video).filter(Video.id == progress.video_id).first()

    if video:
        video.resume_time = progress.current_time
        db.commit()

    return {"success": True}

@api_v1_router.get("/session/state")
@api_legacy_router.get("/session/state")
async def get_session_state(db: Session = Depends(get_db)):
    """Get current session state for restoration."""
    # Get recent videos
    recent = db.query(Video).order_by(Video.created_at.desc()).limit(10).all()

    return {
        "recent_videos": [v.id for v in recent],
        "timestamp": datetime.datetime.now().isoformat()
    }


# ========== BATCH OPERATIONS ==========
class BatchActionRequest(BaseModel):
    video_ids: List[int]
    action: str  # 'favorite', 'delete', 'download', 'refresh'

@api_v1_router.post("/batch/execute")
@api_legacy_router.post("/batch/execute")
async def execute_batch_action(request: BatchActionRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute batch actions on multiple videos."""
    results = {"success": 0, "failed": 0, "errors": []}

    for video_id in request.video_ids:
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                results["failed"] += 1
                results["errors"].append(f"Video {video_id} not found")
                continue

            if request.action == 'favorite':
                video.is_favorite = not video.is_favorite
            elif request.action == 'delete':
                db.delete(video)
            elif request.action == 'download':
                # TODO: Trigger download
                pass
            elif request.action == 'refresh':
                # TODO: Refresh link
                pass

            results["success"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(str(e))

    db.commit()

    return results


from app.routers.proxy import router as proxy_router
from app.routers.imports import router as imports_router
from app.routers.downloads import router as downloads_router
app.include_router(imports_router)
app.include_router(downloads_router)
app.include_router(proxy_router)
app.include_router(api_v1_router)
app.include_router(_modular_api_v1_router)
app.include_router(api_legacy_router)


@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    # Use 8001 as primary port to avoid conflicts
    uvicorn.run(app, host="0.0.0.0", port=8001)