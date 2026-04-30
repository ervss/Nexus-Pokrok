import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video
from app.duplicate_detector import mark_as_duplicate

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

def test_mark_as_duplicate_success(db_session):
    """Test mark_as_duplicate with existing videos"""
    v1 = Video(title="Original", url="url1")
    v2 = Video(title="Duplicate", url="url2")
    db_session.add(v1)
    db_session.add(v2)
    db_session.commit()

    # Reload to get IDs
    original_id = v1.id
    duplicate_id = v2.id

    result = mark_as_duplicate(db_session, duplicate_id, original_id)

    assert result is True

    # Verify in DB
    db_session.expire_all()
    updated_duplicate = db_session.query(Video).get(duplicate_id)
    assert updated_duplicate.duplicate_of == original_id

def test_mark_as_duplicate_not_found(db_session):
    """Test mark_as_duplicate when duplicate video doesn't exist"""
    v1 = Video(title="Original", url="url1")
    db_session.add(v1)
    db_session.commit()

    original_id = v1.id
    non_existent_id = 999

    result = mark_as_duplicate(db_session, non_existent_id, original_id)

    assert result is False
