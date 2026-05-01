import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video
from app.duplicate_detector import (
    compute_phash,
    hamming_distance,
    find_duplicates,
    mark_as_duplicate,
    compute_all_phashes
)
from unittest.mock import patch, MagicMock

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

def test_hamming_distance():
    # Identical hashes
    assert hamming_distance("0000000000000000", "0000000000000000") == 0
    assert hamming_distance("ffffffffffffffff", "ffffffffffffffff") == 0

    # Maximally different hashes (64-bit hashes)
    assert hamming_distance("0000000000000000", "ffffffffffffffff") == 64

    # Known distance
    # 0x01 is 0001, 0x03 is 0011 -> distance 1
    assert hamming_distance("0000000000000001", "0000000000000003") == 1

    # None or empty input
    assert hamming_distance(None, "0000000000000000") == 999
    assert hamming_distance("0000000000000000", "") == 999

    # Invalid hex strings
    assert hamming_distance("invalid", "0000000000000000") == 999

def test_find_duplicates(db_session):
    # Empty database
    assert find_duplicates(db_session) == []

    # Setup videos
    v1 = Video(title="Original", phash="0000000000000000")
    v2 = Video(title="Duplicate", phash="0000000000000001") # distance 1
    v3 = Video(title="Different", phash="ffffffffffffffff") # distance 64
    v4 = Video(title="Already Duplicate", phash="0000000000000000", duplicate_of=1)

    db_session.add_all([v1, v2, v3, v4])
    db_session.commit()

    # Default threshold (5)
    dupes = find_duplicates(db_session)
    assert len(dupes) == 1
    assert dupes[0]['original_id'] == v1.id
    assert dupes[0]['duplicate_id'] == v2.id
    assert dupes[0]['distance'] == 1

    # Strict threshold (0)
    dupes_strict = find_duplicates(db_session, threshold=0)
    assert len(dupes_strict) == 0

    # Loose threshold (64)
    dupes_loose = find_duplicates(db_session, threshold=64)
    # v1-v2, v1-v3, v2-v3
    assert len(dupes_loose) == 3

def test_mark_as_duplicate(db_session):
    v1 = Video(title="Original", url="url1")
    v2 = Video(title="Duplicate", url="url2")
    db_session.add_all([v1, v2])
    db_session.commit()

    # Successful mark
    success = mark_as_duplicate(db_session, v2.id, v1.id)
    assert success is True

    db_session.refresh(v2)
    assert v2.duplicate_of == v1.id

    # Non-existent video
    success = mark_as_duplicate(db_session, 9999, v1.id)
    assert success is False

def test_compute_phash():
    with patch('os.path.exists') as mock_exists, \
         patch('PIL.Image.open') as mock_open, \
         patch('imagehash.phash') as mock_phash:

        # File doesn't exist
        mock_exists.return_value = False
        assert compute_phash("fake.jpg") is None

        # Success
        mock_exists.return_value = True
        mock_hash = MagicMock()
        mock_hash.__str__.return_value = "deadbeef"
        mock_phash.return_value = mock_hash

        assert compute_phash("real.jpg") == "deadbeef"

        # Exception
        mock_open.side_effect = Exception("error")
        assert compute_phash("error.jpg") is None

def test_compute_all_phashes(db_session):
    v1 = Video(title="No Thumb", phash=None, thumbnail_path=None)
    v2 = Video(title="Has Thumb No Phash", phash=None, thumbnail_path="/thumb.jpg")
    v3 = Video(title="Has Phash", phash="already_here", thumbnail_path="/thumb.jpg")

    db_session.add_all([v1, v2, v3])
    db_session.commit()

    with patch('app.duplicate_detector.compute_phash') as mock_compute:
        mock_compute.return_value = "new_hash"

        count = compute_all_phashes(db_session)

        assert count == 1
        db_session.refresh(v2)
        assert v2.phash == "new_hash"

        # Verify compute_phash was called with correct path
        # It prefixes 'app' and removes query params if any
        mock_compute.assert_called_once_with("app/thumb.jpg")
