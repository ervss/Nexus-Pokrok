from pydantic import BaseModel
from typing import List, Optional, Any
import datetime

class VideoExport(BaseModel):
    id: int
    title: str
    url: str
    duration: float
    width: int
    height: int
    tags: str
    ai_tags: str
    created_at: datetime.datetime
    views: Optional[int] = 0
    upload_date: Optional[str] = None
    download_stats: Optional[dict] = None
    storage_type: Optional[str] = "remote"
    status: Optional[str] = "pending"
    batch_name: Optional[str] = None
    class Config:
        from_attributes = True

class ImportRequest(BaseModel):
    urls: List[str]
    items: Optional[List[dict]] = None
    batch_name: Optional[str] = None
    parser: Optional[str] = None
    min_quality: Optional[int] = None
    min_duration: Optional[int] = None
    auto_heal: Optional[bool] = True

class XVideosImportRequest(BaseModel):
    url: str

class SpankBangImportRequest(BaseModel):
    url: str

class BatchActionRequest(BaseModel):
    video_ids: List[int]
    action: str

class BatchRefreshRequest(BaseModel):
    batch_name: str

class BatchDeleteRequest(BaseModel):
    batch_name: str

class VideoUpdate(BaseModel):
    is_favorite: Optional[bool] = None
    is_watched: Optional[bool] = None
    resume_time: Optional[float] = None
    tags: Optional[str] = None
    url: Optional[str] = None

class EpornerSearchRequest(BaseModel):
    query: str
    count: int = 50
    min_quality: int = 1080
    batch_name: Optional[str] = None

class BeegImportRequest(BaseModel):
    query: str
    count: int = 10
    batch_name: Optional[str] = None

class ExternalDownloadRequest(BaseModel):
    url: str
    title: Optional[str] = "External Download"

class EpornerDiscoveryRequest(BaseModel):
    keyword: str
    min_quality: int = 1080
    pages: int = 2
    auto_skip_low_quality: bool = True
    batch_name: Optional[str] = None

class PorntrexDiscoveryRequest(BaseModel):
    keyword: str = ""
    min_quality: int = 1080
    pages: int = 1
    category: str = ""
    upload_type: str = "all"
    auto_skip_low_quality: bool = True
    batch_name: Optional[str] = None

class WhoresHubDiscoveryRequest(BaseModel):
    keyword: str = ""
    tag: str = ""
    min_quality: int = 720
    min_duration: int = 300
    pages: int = 1
    upload_type: str = "all"
    auto_skip_low_quality: bool = True
    batch_name: Optional[str] = None

class TelegramLoginRequest(BaseModel):
    api_id: str
    api_hash: str
    phone: str

class TelegramVerifyRequest(BaseModel):
    code: str
    password: Optional[str] = None

class RedGifsImportRequest(BaseModel):
    keywords: str
    count: int = 20
    hd_only: bool = False
    min_duration: int = 30
    min_resolution: int = 1080
    only_vertical: bool = False
    disable_rejection: bool = False
    batch_name: Optional[str] = None

class RedditImportRequest(BaseModel):
    subreddits: str
    count: int = 20
    hd_only: bool = False
    min_duration: int = 30
    min_resolution: int = 1080
    only_vertical: bool = False
    disable_rejection: bool = False
    batch_name: Optional[str] = None

class PornOneImportRequest(BaseModel):
    keywords: str
    count: int = 20
    min_duration: int = 30
    min_resolution: int = 1080
    only_vertical: bool = False
    batch_name: Optional[str] = None
    debug: bool = False

class XVideosPlaylistImportRequest(BaseModel):
    url: str
    batch_name: Optional[str] = None

class HQPornerImportRequest(BaseModel):
    keywords: str = ""
    category: Optional[str] = None
    min_quality: str = "1080p"
    added_within: str = "any"
    count: int = 20
    batch_name: Optional[str] = None

class TnaflixImportRequest(BaseModel):
    url: Optional[str] = None
    query: Optional[str] = None
    count: int = 20
    min_duration: int = 0
    min_quality: int = 0
    batch_name: Optional[str] = None

class LoginRequest(BaseModel):
    password: str

class BridgeSyncRequest(BaseModel):
    url: str
    cookies: Optional[str] = None
    user_agent: Optional[str] = None
    html_content: Optional[str] = None

class BridgeImportRequest(BaseModel):
    urls: List[str]
    batch_name: str = "Bridge Import"
    cookies: Optional[str] = None

import re

class BulkImportVideo(BaseModel):
    url: str
    title: Optional[str] = None
    source_url: Optional[str] = None
    thumbnail: Optional[str] = None
    filesize: Optional[Any] = 0
    quality: Optional[Any] = 0
    duration: Optional[Any] = 0
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

class DiscoveryProfileCreate(BaseModel):
    name: str
    enabled: bool = True
    schedule_type: str = "interval"
    schedule_value: str = "3600"
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

class VideoProgressUpdate(BaseModel):
    video_id: int
    current_time: float
    duration: float

class WebshareSearchRequest(BaseModel):
    query: str
    limit: int = 20
    sort: str = "recent"
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    offset: int = 0
