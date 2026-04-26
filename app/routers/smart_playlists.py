"""Smart playlist CRUD API."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.smart_playlists import (
    create_preset_playlists,
    create_smart_playlist,
    delete_smart_playlist,
    get_all_smart_playlists,
    get_smart_playlist_videos,
    update_smart_playlist,
)

router = APIRouter(tags=["smart-playlists"])


class SmartPlaylistCreate(BaseModel):
    name: str
    rules: dict


@router.get("/smart-playlists")
def list_smart_playlists(db: Session = Depends(get_db)):
    playlists_data = get_all_smart_playlists(db)
    return Response(content=json.dumps({"playlists": playlists_data}), media_type="application/json")


@router.post("/smart-playlists")
def create_playlist(playlist: SmartPlaylistCreate, db: Session = Depends(get_db)):
    try:
        new_playlist = create_smart_playlist(db, playlist.name, playlist.rules)
        return {"success": True, "playlist_id": new_playlist.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/smart-playlists/{playlist_id}/videos")
def get_playlist_videos(playlist_id: int, db: Session = Depends(get_db)):
    videos = get_smart_playlist_videos(db, playlist_id)
    results = []
    for v in videos:
        video_dict = v.__dict__
        video_dict.pop("_sa_instance_state", None)
        results.append(video_dict)
    return {"videos": results, "count": len(results)}


@router.put("/smart-playlists/{playlist_id}")
def update_playlist(playlist_id: int, playlist: SmartPlaylistCreate, db: Session = Depends(get_db)):
    try:
        update_smart_playlist(db, playlist_id, playlist.name, playlist.rules)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/smart-playlists/{playlist_id}")
def remove_playlist(playlist_id: int, db: Session = Depends(get_db)):
    success = delete_smart_playlist(db, playlist_id)
    if not success:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"success": True}


@router.post("/smart-playlists/create-presets")
def create_presets(db: Session = Depends(get_db)):
    create_preset_playlists(db)
    return {"success": True, "message": "Preset playlists created"}
