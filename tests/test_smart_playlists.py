import pytest
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

def test_evaluate_rule():
    # Mock video object
    class MockVideo:
        def __init__(self, **kwargs):
            self.created_at = datetime.utcnow()
            for k, v in kwargs.items():
                setattr(self, k, v)

    video = MockVideo(title="Test Video", height=1080, is_watched=False)

    # equals
    assert evaluate_rule(video, {'field': 'title', 'operator': 'equals', 'value': 'test video'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'equals', 'value': 'wrong'}) is False

    # not_equals
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_equals', 'value': 'wrong'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_equals', 'value': 'test video'}) is False

    # contains
    assert evaluate_rule(video, {'field': 'title', 'operator': 'contains', 'value': 'Test'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'contains', 'value': 'Wrong'}) is False

    # not_contains
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_contains', 'value': 'Wrong'}) is True
    assert evaluate_rule(video, {'field': 'title', 'operator': 'not_contains', 'value': 'Test'}) is False

    # greater_than
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': '720'}) is True
    assert evaluate_rule(video, {'field': 'height', 'operator': 'greater_than', 'value': '1080'}) is False

    # less_than
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': '2160'}) is True
    assert evaluate_rule(video, {'field': 'height', 'operator': 'less_than', 'value': '1080'}) is False

    # in_last_days
    assert evaluate_rule(video, {'field': 'created_at', 'operator': 'in_last_days', 'value': '1'}) is True
    video_old = MockVideo(created_at=datetime.utcnow() - timedelta(days=5))
    assert evaluate_rule(video_old, {'field': 'created_at', 'operator': 'in_last_days', 'value': '1'}) is False

    # is_true
    video_fav = MockVideo(is_favorite=True)
    assert evaluate_rule(video_fav, {'field': 'is_favorite', 'operator': 'is_true', 'value': ''}) is True
    # If field is missing, getattr returns None, bool(None) is False
    assert evaluate_rule(video, {'field': 'is_favorite', 'operator': 'is_true', 'value': ''}) is False

    # is_false
    assert evaluate_rule(video, {'field': 'is_watched', 'operator': 'is_false', 'value': ''}) is True

def test_get_smart_playlist_videos(db_session):
    v1 = Video(title="HD Video", height=1080, status="ready_to_stream")
    v2 = Video(title="SD Video", height=480, status="ready_to_stream")
    v3 = Video(title="Pending Video", height=1080, status="pending")
    db_session.add_all([v1, v2, v3])
    db_session.commit()

    rules = {
        'match': 'all',
        'rules': [{'field': 'height', 'operator': 'greater_than', 'value': '720'}]
    }
    playlist = SmartPlaylist(name="HD Only", rules=rules)
    db_session.add(playlist)
    db_session.commit()

    videos = get_smart_playlist_videos(db_session, playlist.id)
    assert len(videos) == 1
    assert videos[0].title == "HD Video"

def test_create_smart_playlist(db_session):
    rules = {'match': 'all', 'rules': []}
    playlist = create_smart_playlist(db_session, "New Playlist", rules)
    assert playlist.id is not None
    assert playlist.name == "New Playlist"

    with pytest.raises(ValueError, match="Playlist 'New Playlist' already exists"):
        create_smart_playlist(db_session, "New Playlist", rules)

def test_update_smart_playlist(db_session):
    rules = {'match': 'all', 'rules': []}
    playlist = create_smart_playlist(db_session, "To Update", rules)

    new_rules = {'match': 'any', 'rules': [{'field': 'title', 'operator': 'contains', 'value': 'test'}]}
    updated = update_smart_playlist(db_session, playlist.id, name="Updated Name", rules=new_rules)

    assert updated.name == "Updated Name"
    assert updated.rules['match'] == 'any'

    with pytest.raises(ValueError, match="Playlist not found"):
        update_smart_playlist(db_session, 999, name="Non-existent")

def test_delete_smart_playlist(db_session):
    playlist = create_smart_playlist(db_session, "To Delete", {'match': 'all', 'rules': []})
    assert delete_smart_playlist(db_session, playlist.id) is True
    # Re-fetch to confirm it's gone
    assert db_session.query(SmartPlaylist).get(playlist.id) is None
    assert delete_smart_playlist(db_session, 999) is False

def test_get_all_smart_playlists(db_session):
    # Empty case
    assert get_all_smart_playlists(db_session) == []

    # With data
    v1 = Video(title="Video 1", status="ready_to_stream")
    db_session.add(v1)
    db_session.commit()

    create_smart_playlist(db_session, "Playlist 1", {'match': 'all', 'rules': []})
    create_smart_playlist(db_session, "Playlist 2", {
        'match': 'all',
        'rules': [{'field': 'title', 'operator': 'contains', 'value': 'Video 1'}]
    })

    results = get_all_smart_playlists(db_session)
    assert len(results) == 2

    p1 = next(r for r in results if r['name'] == "Playlist 1")
    assert p1['video_count'] == 1 # Empty rules matches all ready videos

    p2 = next(r for r in results if r['name'] == "Playlist 2")
    assert p2['video_count'] == 1

    # Check fields
    assert 'id' in p1
    assert 'rules' in p1
    assert 'created_at' in p1
