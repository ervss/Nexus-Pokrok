import pytest
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, SmartPlaylist
from app.smart_playlists import update_smart_playlist

# Set required environment variables for configuration initialization
os.environ['DASHBOARD_PASSWORD'] = "StrongPassword123!"
os.environ['SECRET_KEY'] = "a_very_secret_key_at_least_32_chars_long"

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

def test_update_smart_playlist_success(db_session):
    # Create initial playlist
    original_rules = {"match": "all", "rules": []}
    playlist = SmartPlaylist(name="Original", rules=original_rules)
    db_session.add(playlist)
    db_session.commit()
    db_session.refresh(playlist)

    playlist_id = playlist.id

    # Update both name and rules
    new_name = "Updated"
    new_rules = {"match": "any", "rules": []}
    updated_playlist = update_smart_playlist(db_session, playlist_id, name=new_name, rules=new_rules)

    assert updated_playlist.name == new_name
    assert updated_playlist.rules == new_rules

    # Verify in database
    db_playlist = db_session.query(SmartPlaylist).get(playlist_id)
    assert db_playlist.name == new_name
    assert db_playlist.rules == new_rules

def test_update_smart_playlist_name_only(db_session):
    original_rules = {"match": "all", "rules": []}
    playlist = SmartPlaylist(name="Original Name", rules=original_rules)
    db_session.add(playlist)
    db_session.commit()

    playlist_id = playlist.id
    new_name = "New Name"
    update_smart_playlist(db_session, playlist_id, name=new_name)

    db_playlist = db_session.query(SmartPlaylist).get(playlist_id)
    assert db_playlist.name == new_name
    assert db_playlist.rules == original_rules

def test_update_smart_playlist_rules_only(db_session):
    original_name = "Same Name"
    original_rules = {"match": "all", "rules": []}
    playlist = SmartPlaylist(name=original_name, rules=original_rules)
    db_session.add(playlist)
    db_session.commit()

    playlist_id = playlist.id
    new_rules = {"match": "any", "rules": [{"field": "title", "operator": "contains", "value": "test"}]}
    update_smart_playlist(db_session, playlist_id, rules=new_rules)

    db_playlist = db_session.query(SmartPlaylist).get(playlist_id)
    assert db_playlist.name == original_name
    assert db_playlist.rules == new_rules

def test_update_smart_playlist_not_found(db_session):
    with pytest.raises(ValueError) as excinfo:
        update_smart_playlist(db_session, 999, name="Does not exist")
    assert str(excinfo.value) == "Playlist not found"
