from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import get_db, Video
from pydantic import BaseModel
import os
import asyncio
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, VectorParams, Distance
from sentence_transformers import SentenceTransformer

router = APIRouter(prefix="/semantic", tags=["semantic"])

# Lazy initialization for ML models so startup is not blocked
qdrant = None
model = None
collection_name = "videos_collection"

def get_ai_models():
    global qdrant, model
    if qdrant is None or model is None:
        try:
            # Use persistent storage
            qdrant_path = "qdrant_data"
            os.makedirs(qdrant_path, exist_ok=True)
            qdrant = QdrantClient(path=qdrant_path)

            # Ensure collection exists
            try:
                qdrant.get_collection(collection_name)
            except Exception:
                qdrant.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )

            model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            print(f"Failed to initialize AI search components: {e}")
            qdrant = None
            model = None
    return qdrant, model

class SemanticSearchRequest(BaseModel):
    query: str
    limit: int = 12

@router.post("/search")
async def semantic_search(req: SemanticSearchRequest, db: Session = Depends(get_db)):
    q, m = get_ai_models()
    if not q or not m:
        raise HTTPException(status_code=503, detail="AI Search engine is not available")

    # Generate embedding for the query
    vector = await asyncio.to_thread(lambda: m.encode(req.query).tolist())

    # Search in Qdrant
    search_result = q.search(
        collection_name=collection_name,
        query_vector=vector,
        limit=req.limit
    )

    video_ids = [hit.payload["video_id"] for hit in search_result]
    scores = {hit.payload["video_id"]: hit.score for hit in search_result}

    if not video_ids:
        return {"query": req.query, "results": []}

    # Fetch from DB
    videos = db.query(Video).filter(Video.id.in_(video_ids)).all()

    # Sort by score
    videos.sort(key=lambda x: scores.get(x.id, 0), reverse=True)

    return {
        "query": req.query,
        "results": [
            {
                "id": v.id,
                "title": v.title,
                "thumbnail_path": v.thumbnail_path,
                "duration": v.duration,
                "score": scores.get(v.id, 0)
            } for v in videos
        ]
    }

@router.post("/index_all")
def index_all_videos(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    q, m = get_ai_models()
    if not q or not m:
        raise HTTPException(status_code=503, detail="AI Search engine is not available")

    videos = db.query(Video).all()

    # Extract data to avoid DetachedInstanceError in background task
    video_data = [
        {
            "id": v.id,
            "title": v.title or "",
            "tags": v.tags or "",
            "ai_tags": v.ai_tags or ""
        } for v in videos
    ]

    def process_indexing(v_data):
        points = []
        for i, v in enumerate(v_data):
            # Combine title and tags for richer semantics
            text = f"{v['title']}. Tags: {v['tags']} {v['ai_tags']}"
            vector = m.encode(text).tolist()

            points.append(PointStruct(
                id=v["id"],
                vector=vector,
                payload={"video_id": v["id"], "title": v["title"]}
            ))

            # Batch upsert
            if len(points) >= 50 or i == len(v_data) - 1:
                if points:
                    q.upsert(collection_name=collection_name, points=points)
                points = []

    background_tasks.add_task(process_indexing, video_data)
    return {"message": f"Indexing {len(video_data)} videos in background"}
