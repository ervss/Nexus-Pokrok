import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video
from app.maintenance import get_duplicates_by_name, get_duplicates_by_hash

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

def test_get_duplicates_by_name_empty(db_session):
    """Test get_duplicates_by_name with an empty database"""
    results = get_duplicates_by_name(db_session)
    assert results == []

def test_get_duplicates_by_name_no_duplicates(db_session):
    """Test get_duplicates_by_name with no duplicates"""
    v1 = Video(title="Video 1", url="url1", status="ready")
    v2 = Video(title="Video 2", url="url2", status="ready")
    db_session.add(v1)
    db_session.add(v2)
    db_session.commit()

    results = get_duplicates_by_name(db_session)
    assert results == []

def test_get_duplicates_by_name_with_duplicates(db_session):
    """Test get_duplicates_by_name with actual duplicates"""
    # Group 1: 2 duplicates
    v1 = Video(title="Duplicate 1", url="url1", height=720, width=1280, duration=100, status="ready", batch_name="batch1")
    v2 = Video(title="Duplicate 1", url="url2", height=1080, width=1920, duration=100, status="ready", batch_name="batch2")

    # Group 2: 3 duplicates
    v3 = Video(title="Duplicate 2", url="url3", height=480, width=640, duration=50, status="ready", batch_name="batch1")
    v4 = Video(title="Duplicate 2", url="url4", height=480, width=640, duration=50, status="ready", batch_name="batch1")
    v5 = Video(title="Duplicate 2", url="url5", height=480, width=640, duration=55, status="ready", batch_name="batch3")

    # Unique video
    v6 = Video(title="Unique", url="url6", status="ready")

    db_session.add_all([v1, v2, v3, v4, v5, v6])
    db_session.commit()

    results = get_duplicates_by_name(db_session)

    assert len(results) == 2

    # Check "Duplicate 1" group
    dup1 = next(r for r in results if r["title"] == "Duplicate 1")
    assert dup1["count"] == 2
    assert len(dup1["videos"]) == 2
    ids1 = [v["id"] for v in dup1["videos"]]
    assert v1.id in ids1
    assert v2.id in ids1

    # Check "Duplicate 2" group
    dup2 = next(r for r in results if r["title"] == "Duplicate 2")
    assert dup2["count"] == 3
    assert len(dup2["videos"]) == 3
    ids2 = [v["id"] for v in dup2["videos"]]
    assert v3.id in ids2
    assert v4.id in ids2
    assert v5.id in ids2

    # Verify metadata in results
    v2_meta = next(v for v in dup1["videos"] if v["id"] == v2.id)
    assert v2_meta["height"] == 1080
    assert v2_meta["width"] == 1920
    assert v2_meta["batch"] == "batch2"

def test_get_duplicates_by_hash_empty(db_session):
    """Test get_duplicates_by_hash with an empty database"""
    results = get_duplicates_by_hash(db_session)
    assert results == []

def test_get_duplicates_by_hash_no_phashes(db_session):
    """Test get_duplicates_by_hash with videos having no phash"""
    v1 = Video(title="Video 1", url="url1", status="ready")
    v2 = Video(title="Video 2", url="url2", status="ready")
    db_session.add_all([v1, v2])
    db_session.commit()

    results = get_duplicates_by_hash(db_session)
    assert results == []

def test_get_duplicates_by_hash_no_duplicates(db_session):
    """Test get_duplicates_by_hash with no duplicates (high hamming distance)"""
    # phashes are 64-bit hex strings.
    # ffffffffffffffff and 0000000000000000 have distance 64.
    v1 = Video(title="Video 1", url="url1", phash="ffffffffffffffff", status="ready")
    v2 = Video(title="Video 2", url="url2", phash="0000000000000000", status="ready")
    db_session.add_all([v1, v2])
    db_session.commit()

    results = get_duplicates_by_hash(db_session, threshold=5)
    assert results == []

def test_get_duplicates_by_hash_with_duplicates(db_session):
    """Test get_duplicates_by_hash with actual duplicates"""
    # Identical phashes (distance 0)
    v1 = Video(title="Video 1", url="url1", phash="a1b2c3d4e5f60718", height=720, width=1280, duration=100, status="ready", batch_name="batch1")
    v2 = Video(title="Video 1 Dup", url="url2", phash="a1b2c3d4e5f60718", height=1080, width=1920, duration=100, status="ready", batch_name="batch2")

    # Similar phashes (distance <= threshold)
    # a1b2c3d4e5f60718 vs a1b2c3d4e5f60719 (last nibble 8 -> 9 is 1 bit difference)
    v3 = Video(title="Video 3", url="url3", phash="a1b2c3d4e5f60719", height=480, width=640, duration=50, status="ready", batch_name="batch1")

    # Another group
    v4 = Video(title="Video 4", url="url4", phash="ffff0000ffff0000", status="ready")
    v5 = Video(title="Video 4 Dup", url="url5", phash="ffff0000ffff0001", status="ready") # 1 bit diff

    # Unique
    v6 = Video(title="Unique", url="url6", phash="0000ffff0000ffff", status="ready")

    db_session.add_all([v1, v2, v3, v4, v5, v6])
    db_session.commit()

    # With threshold 5, v1, v2, v3 should be in one group. v4, v5 in another.
    results = get_duplicates_by_hash(db_session, threshold=5)

    assert len(results) == 2

    # Check first group (v1, v2, v3)
    # The first video encountered (v1) becomes the representative
    group1 = next(r for r in results if r["representative"] == "Video 1")
    assert group1["count"] == 3
    ids1 = [v["id"] for v in group1["videos"]]
    assert v1.id in ids1
    assert v2.id in ids1
    assert v3.id in ids1

    # Check second group (v4, v5)
    group2 = next(r for r in results if r["representative"] == "Video 4")
    assert group2["count"] == 2
    ids2 = [v["id"] for v in group2["videos"]]
    assert v4.id in ids2
    assert v5.id in ids2

def test_get_duplicates_by_hash_threshold_effect(db_session):
    """Test how threshold affects results"""
    # a1b2c3d4e5f60718 vs a1b2c3d4e5f6071f
    # 8 = 1000, f = 1111 -> 3 bits difference
    v1 = Video(title="Video 1", url="url1", phash="a1b2c3d4e5f60718", status="ready")
    v2 = Video(title="Video 2", url="url2", phash="a1b2c3d4e5f6071f", status="ready")

    db_session.add_all([v1, v2])
    db_session.commit()

    # Threshold 2: should not find duplicates
    assert get_duplicates_by_hash(db_session, threshold=2) == []

    # Threshold 3: should find duplicates
    results = get_duplicates_by_hash(db_session, threshold=3)
    assert len(results) == 1
    assert results[0]["count"] == 2
