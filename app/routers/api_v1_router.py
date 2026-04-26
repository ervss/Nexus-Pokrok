from fastapi import APIRouter
from app.routers import duplicates, library_health, maintenance_endpoints, smart_playlists, semantic_search

router = APIRouter(prefix="/api/v1")

router.include_router(duplicates.router)
router.include_router(library_health.router)
router.include_router(maintenance_endpoints.router)
router.include_router(smart_playlists.router)
router.include_router(semantic_search.router)
