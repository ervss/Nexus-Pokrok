import pytest
from datetime import datetime, timedelta
from app.database import Video
from app.smart_playlists import evaluate_rule

def test_evaluate_rule_missing_field_or_operator():
    video = Video(title="Test Video")
    # Should return True if field or operator is missing
    assert evaluate_rule(video, {}) is True
    assert evaluate_rule(video, {'field': 'title'}) is True
    assert evaluate_rule(video, {'operator': 'equals'}) is True

def test_evaluate_rule_equals():
    video = Video(title="Test Video", height=1080)
    # Case insensitive string comparison
    assert evaluate_rule(video, {'field': 'title', 'operator': 'equals', 'value': 'test video'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'equals', 'value': 'Wrong'}) is False
    # Numeric values converted to string
    assert evaluate_rule(video, {'field': 'height', 'operator': 'equals', 'value': '1080'}) is True
    assert evaluate_rule(video, {'field': 'height', 'operator': 'equals', 'value': '720'}) is False

def test_evaluate_rule_not_equals():
    video = Video(title="Test Video")
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_equals', 'value': 'Wrong'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_equals', 'value': 'test video'}) is False

def test_evaluate_rule_contains():
    video = Video(title="Test Video")
    assert evaluate_rule(video, {'field': 'title', 'operator': 'contains', 'value': 'test'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'contains', 'value': 'TEST'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'contains', 'value': 'Wrong'}) is False

def test_evaluate_rule_not_contains():
    video = Video(title="Test Video")
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_contains', 'value': 'Wrong'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_contains', 'value': 'test'}) is False

def test_evaluate_rule_greater_than():
    video = Video(height=1080)
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': '720'}) is True
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': '1080'}) is False
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': '2000'}) is False
    # Invalid numeric value should return False
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': 'abc'}) is False

def test_evaluate_rule_less_than():
    video = Video(height=720)
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': '1080'}) is True
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': '720'}) is False
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': '480'}) is False
    # Invalid numeric value should return False
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': 'abc'}) is False

def test_evaluate_rule_in_last_days():
    now = datetime.utcnow()
    video_recent = Video(created_at=now - timedelta(days=2))
    video_old = Video(created_at=now - timedelta(days=10))

    assert evaluate_rule(video_recent, {'field': 'created_at', 'operator': 'in_last_days', 'value': '7'}) is True
    assert evaluate_rule(video_old, {'field': 'created_at', 'operator': 'in_last_days', 'value': '7'}) is False
    # Invalid integer value should return False
    assert evaluate_rule(video_recent, {'field': 'created_at', 'operator': 'in_last_days', 'value': 'abc'}) is False

def test_evaluate_rule_is_true():
    video_fav = Video(is_favorite=True)
    video_not_fav = Video(is_favorite=False)
    assert evaluate_rule(video_fav, {'field': 'is_favorite', 'operator': 'is_true', 'value': ''}) is True
    assert evaluate_rule(video_not_fav, {'field': 'is_favorite', 'operator': 'is_true', 'value': ''}) is False

def test_evaluate_rule_is_false():
    video_fav = Video(is_favorite=True)
    video_not_fav = Video(is_favorite=False)
    assert evaluate_rule(video_fav, {'field': 'is_favorite', 'operator': 'is_false', 'value': ''}) is False
    assert evaluate_rule(video_not_fav, {'field': 'is_favorite', 'operator': 'is_false', 'value': ''}) is True

def test_evaluate_rule_unknown_operator():
    video = Video(title="Test")
    # Unknown operator returns True by default in the implementation
    assert evaluate_rule(video, {'field': 'title', 'operator': 'unknown', 'value': 'val'}) is True
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video, SmartPlaylist
from app.smart_playlists import (
    evaluate_rule,
    get_smart_playlist_videos,
    create_smart_playlist,
    update_smart_playlist,
    delete_smart_playlist,
    get_all_smart_playlists
)
from datetime import datetime, timedelta

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

def test_delete_smart_playlist_success(db_session):
    """Test successful deletion of a smart playlist"""
    playlist = SmartPlaylist(name="To Delete", rules={"match": "all", "rules": []})
    db_session.add(playlist)
    db_session.commit()
    playlist_id = playlist.id

    result = delete_smart_playlist(db_session, playlist_id)

    assert result is True
    deleted_playlist = db_session.query(SmartPlaylist).get(playlist_id)
    assert deleted_playlist is None

def test_delete_smart_playlist_not_found(db_session):
    """Test deletion of a non-existent smart playlist"""
    result = delete_smart_playlist(db_session, 999)
    assert result is False

def test_create_smart_playlist_success(db_session):
    """Test successful creation of a smart playlist"""
    name = "New Playlist"
    rules = {"match": "all", "rules": [{"field": "title", "operator": "contains", "value": "test"}]}

    playlist = create_smart_playlist(db_session, name, rules)

    assert playlist.id is not None
    assert playlist.name == name
    assert playlist.rules == rules

    # Verify in DB
    db_playlist = db_session.query(SmartPlaylist).filter_by(name=name).first()
    assert db_playlist is not None
    assert db_playlist.id == playlist.id

def test_create_smart_playlist_duplicate_name(db_session):
    """Test creation with a duplicate name raises ValueError"""
    name = "Duplicate"
    rules = {"match": "all", "rules": []}
    create_smart_playlist(db_session, name, rules)

    with pytest.raises(ValueError, match=f"Playlist '{name}' already exists"):
        create_smart_playlist(db_session, name, rules)

def test_update_smart_playlist_success(db_session):
    """Test successful update of a smart playlist"""
    playlist = SmartPlaylist(name="Old Name", rules={"match": "all", "rules": []})
    db_session.add(playlist)
    db_session.commit()

    new_name = "Updated Name"
    new_rules = {"match": "any", "rules": [{"field": "id", "operator": "equals", "value": "1"}]}

    updated = update_smart_playlist(db_session, playlist.id, name=new_name, rules=new_rules)

    assert updated.name == new_name
    assert updated.rules == new_rules

    # Verify in DB
    db_playlist = db_session.query(SmartPlaylist).get(playlist.id)
    assert db_playlist.name == new_name
    assert db_playlist.rules == new_rules

def test_update_smart_playlist_not_found(db_session):
    """Test update of a non-existent smart playlist raises ValueError"""
    with pytest.raises(ValueError, match="Playlist not found"):
        update_smart_playlist(db_session, 999, name="Doesn't matter")

def test_evaluate_rule_operators():
    """Test various operators in evaluate_rule"""
    video = Video(
        title="Test Video",
        duration=100.0,
        is_favorite=True,
        created_at=datetime.utcnow() - timedelta(days=5)
    )

    # equals
    assert evaluate_rule(video, {"field": "title", "operator": "equals", "value": "Test Video"}) is True
    assert evaluate_rule(video, {"field": "title", "operator": "equals", "value": "wrong"}) is False

    # not_equals
    assert evaluate_rule(video, {"field": "title", "operator": "not_equals", "value": "wrong"}) is True
    assert evaluate_rule(video, {"field": "title", "operator": "not_equals", "value": "Test Video"}) is False

    # contains
    assert evaluate_rule(video, {"field": "title", "operator": "contains", "value": "Test"}) is True
    assert evaluate_rule(video, {"field": "title", "operator": "contains", "value": "wrong"}) is False

    # not_contains
    assert evaluate_rule(video, {"field": "title", "operator": "not_contains", "value": "wrong"}) is True
    assert evaluate_rule(video, {"field": "title", "operator": "not_contains", "value": "Test"}) is False

    # greater_than
    assert evaluate_rule(video, {"field": "duration", "operator": "greater_than", "value": "50"}) is True
    assert evaluate_rule(video, {"field": "duration", "operator": "greater_than", "value": "150"}) is False

    # less_than
    assert evaluate_rule(video, {"field": "duration", "operator": "less_than", "value": "150"}) is True
    assert evaluate_rule(video, {"field": "duration", "operator": "less_than", "value": "50"}) is False

    # in_last_days
    assert evaluate_rule(video, {"field": "created_at", "operator": "in_last_days", "value": "10"}) is True
    assert evaluate_rule(video, {"field": "created_at", "operator": "in_last_days", "value": "2"}) is False

    # is_true
    assert evaluate_rule(video, {"field": "is_favorite", "operator": "is_true", "value": ""}) is True

    # is_false
    assert evaluate_rule(video, {"field": "is_favorite", "operator": "is_false", "value": ""}) is False

def test_get_smart_playlist_videos_filtering(db_session):
    """Test get_smart_playlist_videos filtering logic"""
    # Create videos
    v1 = Video(title="Alpha", status="ready_to_stream", duration=100)
    v2 = Video(title="Beta", status="ready_to_stream", duration=200)
    v3 = Video(title="Gamma", status="pending", duration=300) # Should be ignored (not ready_to_stream)
    db_session.add_all([v1, v2, v3])
    db_session.commit()

    # Playlist with 'all' match
    p1 = SmartPlaylist(name="All Match", rules={
        "match": "all",
        "rules": [
            {"field": "title", "operator": "contains", "value": "Alp"},
            {"field": "duration", "operator": "greater_than", "value": "50"}
        ]
    })
    db_session.add(p1)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, p1.id)
    assert len(videos) == 1
    assert videos[0].title == "Alpha"

    # Playlist with 'any' match
    p2 = SmartPlaylist(name="Any Match", rules={
        "match": "any",
        "rules": [
            {"field": "title", "operator": "equals", "value": "Alpha"},
            {"field": "title", "operator": "equals", "value": "Beta"}
        ]
    })
    db_session.add(p2)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, p2.id)
    assert len(videos) == 2
