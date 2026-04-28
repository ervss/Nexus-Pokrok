from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, Text, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from sqlalchemy import event

from .config import config

SQLALCHEMY_DATABASE_URL = config.DATABASE_URL

_is_sqlite = (SQLALCHEMY_DATABASE_URL or "").strip().lower().startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args=_connect_args,
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_timeout=config.DB_POOL_TIMEOUT,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    url = Column(String)
    source_url = Column(String) # For JIT link refreshing
    thumbnail_path = Column(String)
    gif_preview_path = Column(String)
    preview_path = Column(String)
    duration = Column(Float, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    aspect_ratio = Column(String, nullable=True)  # "16:9", "9:16", "4:3", "1:1", etc.
    batch_name = Column(String, index=True)
    tags = Column(String, default="") 
    ai_tags = Column(String, default="")
    subtitle = Column(Text, default="")
    sprite_path = Column(String, nullable=True)
    storage_type = Column(String, default="remote") # "remote" or "local"
    is_favorite = Column(Boolean, default=False)
    is_watched = Column(Boolean, default=False)
    resume_time = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending") # pending, processing, ready, error
    error_msg = Column(Text, nullable=True)

    # Health monitoring fields
    last_checked = Column(DateTime, nullable=True)
    link_status = Column(String, default="unknown") # unknown, working, broken
    check_count = Column(Integer, default=0)
    
    # Stats
    download_stats = Column(JSON, nullable=True)
    views = Column(Integer, default=0)
    upload_date = Column(String, nullable=True)
    phash = Column(String, nullable=True)
    duplicate_of = Column(Integer, nullable=True)


class SmartPlaylist(Base):
    __tablename__ = "smart_playlists"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True)
    rules = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class SearchHistory(Base):
    __tablename__ = "search_history"
    id = Column(Integer, primary_key=True, index=True)
    query = Column(String, index=True)
    source = Column(String, nullable=True)
    results_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class DiscoveryProfile(Base):
    __tablename__ = "discovery_profiles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True)
    enabled = Column(Boolean, default=True)
    schedule_type = Column(String, default="interval")
    schedule_value = Column(String, default="3600")
    keywords = Column(String, default="")
    exclude_keywords = Column(String, default="")
    sources = Column(JSON, default=list)
    min_height = Column(Integer, nullable=True)
    max_height = Column(Integer, nullable=True)
    aspect_ratio = Column(String, nullable=True)
    min_duration = Column(Integer, nullable=True)
    max_duration = Column(Integer, nullable=True)
    max_results = Column(Integer, default=20)
    auto_import = Column(Boolean, default=False)
    batch_prefix = Column(String, default="Auto")
    last_run = Column(DateTime, nullable=True)
    total_runs = Column(Integer, default=0)
    total_found = Column(Integer, default=0)
    total_imported = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DiscoveryNotification(Base):
    __tablename__ = "discovery_notifications"
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, index=True)
    profile_name = Column(String)
    notification_type = Column(String)
    message = Column(Text)
    video_count = Column(Integer, default=0)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class DiscoveredVideo(Base):
    __tablename__ = "discovered_videos"
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, index=True)
    profile_name = Column(String)
    title = Column(String)
    url = Column(String, index=True)
    source_url = Column(String)
    thumbnail = Column(String)
    duration = Column(Float, default=0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    source = Column(String)
    imported = Column(Boolean, default=False)
    video_id = Column(Integer, nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    imported_at = Column(DateTime, nullable=True)


def init_db():
    global _is_sqlite
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if not inspector.has_table("videos"):
        Base.metadata.create_all(bind=engine)
    else:
        columns = [c['name'] for c in inspector.get_columns('videos')]
        if 'sprite_path' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN sprite_path VARCHAR'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'source_url' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN source_url VARCHAR'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'storage_type' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN storage_type VARCHAR DEFAULT "remote"'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'phash' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN phash VARCHAR'))
                        connection.execute(text('CREATE INDEX IF NOT EXISTS idx_phash ON videos(phash)'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'duplicate_of' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN duplicate_of INTEGER'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'last_checked' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN last_checked DATETIME'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'link_status' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN link_status VARCHAR DEFAULT "unknown"'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'check_count' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN check_count INTEGER DEFAULT 0'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'download_stats' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN download_stats JSON'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'aspect_ratio' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN aspect_ratio VARCHAR'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'views' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN views INTEGER DEFAULT 0'))
            except Exception as e:
                print("Ignored schema alter:", e)
        if 'upload_date' not in columns:
            try:
                with engine.connect() as connection:
                    if _is_sqlite:
                        connection.execute(text('ALTER TABLE videos ADD COLUMN upload_date VARCHAR'))
            except Exception as e:
                print("Ignored schema alter:", e)

    if not inspector.has_table("smart_playlists"):
         Base.metadata.create_all(bind=engine)

    if not inspector.has_table("search_history"):
         Base.metadata.create_all(bind=engine)

    if not inspector.has_table("discovery_profiles"):
         Base.metadata.create_all(bind=engine)

    if not inspector.has_table("discovery_notifications"):
         Base.metadata.create_all(bind=engine)

    if not inspector.has_table("discovered_videos"):
         Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def get_db_health() -> dict:
    """
    Check database health and return status information.
    
    Returns:
        Dictionary with health check results
    """
    health = {
        "status": "unknown",
        "database_exists": False,
        "database_size_mb": 0,
        "tables": [],
        "total_videos": 0,
        "connection_pool": {},
        "errors": []
    }
    
    try:
        from sqlalchemy import inspect
        import os
        
        # Check if database file exists
        db_path = SQLALCHEMY_DATABASE_URL.replace('sqlite:///', '')
        if os.path.exists(db_path):
            health["database_exists"] = True
            health["database_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        elif not _is_sqlite:
            health["database_exists"] = True
        
        # Check connection and schema
        inspector = inspect(engine)
        health["tables"] = inspector.get_table_names()
        
        # Get pool statistics
        pool = engine.pool
        health["connection_pool"] = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "max_overflow": pool._max_overflow if hasattr(pool, '_max_overflow') else 0
        }
        
        # Count videos
        db = SessionLocal()
        try:
            health["total_videos"] = db.query(Video).count()
        finally:
            db.close()
        
        health["status"] = "healthy"
        
    except Exception as e:
        health["status"] = "unhealthy"
        health["errors"].append(str(e))
    
    return health


def get_migration_version() -> dict:
    """
    Get current Alembic migration version.
    
    Returns:
        Dictionary with version information
    """
    version_info = {
        "current_revision": None,
        "is_up_to_date": False,
        "error": None
    }
    
    try:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.migration import MigrationContext
        
        # Get current revision from database
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
            version_info["current_revision"] = current_rev
        
        # Check if up to date
        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()
        
        version_info["head_revision"] = head_rev
        version_info["is_up_to_date"] = (current_rev == head_rev)
        
    except Exception as e:
        version_info["error"] = str(e)
    
    return version_info
