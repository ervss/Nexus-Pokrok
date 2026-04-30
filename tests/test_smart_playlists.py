import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from app.database import Base, Video, SmartPlaylist
from app.smart_playlists import get_smart_playlist_videos

# Setup in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

def test_get_smart_playlist_videos_not_found(db_session):
    """Test get_smart_playlist_videos when playlist does not exist"""
    videos = get_smart_playlist_videos(db_session, 999)
    assert videos == []

def test_get_smart_playlist_videos_status_ready_to_stream(db_session):
    """Test that only videos with status 'ready_to_stream' are returned"""
    v1 = Video(title="Ready", status="ready_to_stream")
    v2 = Video(title="Pending", status="pending")
    db_session.add_all([v1, v2])

    playlist = SmartPlaylist(name="All", rules={"match": "all", "rules": []})
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "Ready"

def test_get_smart_playlist_videos_all_match(db_session):
    """Test 'all' match type"""
    v1 = Video(title="HD Video", height=1080, status="ready_to_stream")
    v2 = Video(title="SD Video", height=480, status="ready_to_stream")
    db_session.add_all([v1, v2])

    # Playlist: height > 720 AND title contains "HD"
    rules = {
        "match": "all",
        "rules": [
            {"field": "height", "operator": "greater_than", "value": "720"},
            {"field": "title", "operator": "contains", "value": "HD"}
        ]
    }
    playlist = SmartPlaylist(name="HD Videos", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "HD Video"

def test_get_smart_playlist_videos_any_match(db_session):
    """Test 'any' match type"""
    v1 = Video(title="Favorite Video", is_favorite=True, status="ready_to_stream")
    v2 = Video(title="HD Video", height=1080, is_favorite=False, status="ready_to_stream")
    v3 = Video(title="Regular Video", height=480, is_favorite=False, status="ready_to_stream")
    db_session.add_all([v1, v2, v3])

    # Playlist: is_favorite=True OR height > 720
    rules = {
        "match": "any",
        "rules": [
            {"field": "is_favorite", "operator": "is_true", "value": ""},
            {"field": "height", "operator": "greater_than", "value": "720"}
        ]
    }
    playlist = SmartPlaylist(name="Fav or HD", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 2
    titles = [v.title for v in videos]
    assert "Favorite Video" in titles
    assert "HD Video" in titles

def test_evaluate_rule_in_last_days(db_session):
    """Test 'in_last_days' operator"""
    now = datetime.utcnow()
    v1 = Video(title="Recent", created_at=now - timedelta(days=2), status="ready_to_stream")
    v2 = Video(title="Old", created_at=now - timedelta(days=10), status="ready_to_stream")
    db_session.add_all([v1, v2])

    rules = {
        "match": "all",
        "rules": [{"field": "created_at", "operator": "in_last_days", "value": "5"}]
    }
    playlist = SmartPlaylist(name="Recent", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "Recent"

def test_evaluate_rule_not_equals_and_is_false(db_session):
    """Test 'not_equals' and 'is_false' operators"""
    v1 = Video(title="Video A", is_watched=True, status="ready_to_stream")
    v2 = Video(title="Video B", is_watched=False, status="ready_to_stream")
    v3 = Video(title="Video C", is_watched=False, status="ready_to_stream")
    db_session.add_all([v1, v2, v3])

    rules = {
        "match": "all",
        "rules": [
            {"field": "title", "operator": "not_equals", "value": "Video A"},
            {"field": "is_watched", "operator": "is_false", "value": ""}
        ]
    }
    playlist = SmartPlaylist(name="Unwatched not A", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 2
    titles = [v.title for v in videos]
    assert "Video B" in titles
    assert "Video C" in titles

def test_evaluate_rule_less_than(db_session):
    """Test 'less_than' operator"""
    v1 = Video(title="Short", duration=100, status="ready_to_stream")
    v2 = Video(title="Long", duration=1000, status="ready_to_stream")
    db_session.add_all([v1, v2])

    rules = {
        "match": "all",
        "rules": [{"field": "duration", "operator": "less_than", "value": "500"}]
    }
    playlist = SmartPlaylist(name="Short Videos", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "Short"

def test_evaluate_rule_not_contains(db_session):
    """Test 'not_contains' operator"""
    v1 = Video(title="Apple", status="ready_to_stream")
    v2 = Video(title="Banana", status="ready_to_stream")
    db_session.add_all([v1, v2])

    rules = {
        "match": "all",
        "rules": [{"field": "title", "operator": "not_contains", "value": "Apple"}]
    }
    playlist = SmartPlaylist(name="No Apples", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "Banana"
