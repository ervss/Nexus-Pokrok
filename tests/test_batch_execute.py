import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, Video
from app.main import execute_batch_action, BatchActionRequest
from unittest.mock import MagicMock, patch

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

@pytest.mark.asyncio
async def test_execute_batch_action_favorite(db_session):
    v1 = Video(title="Video 1", url="url1", is_favorite=False)
    v2 = Video(title="Video 2", url="url2", is_favorite=True)
    db_session.add_all([v1, v2])
    db_session.commit()

    request = BatchActionRequest(video_ids=[v1.id, v2.id], action='favorite')
    background_tasks = MagicMock()

    results = await execute_batch_action(request, background_tasks, db_session)

    assert results["success"] == 2
    assert v1.is_favorite is True
    assert v2.is_favorite is False

@pytest.mark.asyncio
async def test_execute_batch_action_delete(db_session):
    v1 = Video(title="Video 1", url="url1")
    db_session.add(v1)
    db_session.commit()

    request = BatchActionRequest(video_ids=[v1.id], action='delete')
    background_tasks = MagicMock()

    results = await execute_batch_action(request, background_tasks, db_session)

    assert results["success"] == 1
    assert db_session.query(Video).filter(Video.id == v1.id).first() is None

@pytest.mark.asyncio
@patch("app.workers.tasks.process_video_task.delay")
async def test_execute_batch_action_download(mock_delay, db_session):
    v1 = Video(title="Video 1", url="url1")
    db_session.add(v1)
    db_session.commit()

    request = BatchActionRequest(video_ids=[v1.id], action='download')
    background_tasks = MagicMock()

    results = await execute_batch_action(request, background_tasks, db_session)

    assert results["success"] == 1
    mock_delay.assert_called_once_with(v1.id)

@pytest.mark.asyncio
@patch("app.workers.tasks.refresh_video_link_task.delay")
async def test_execute_batch_action_refresh(mock_delay, db_session):
    v1 = Video(title="Video 1", url="url1")
    db_session.add(v1)
    db_session.commit()

    request = BatchActionRequest(video_ids=[v1.id], action='refresh')
    background_tasks = MagicMock()

    results = await execute_batch_action(request, background_tasks, db_session)

    assert results["success"] == 1
    mock_delay.assert_called_once_with(v1.id)

@pytest.mark.asyncio
async def test_execute_batch_action_not_found(db_session):
    request = BatchActionRequest(video_ids=[999], action='favorite')
    background_tasks = MagicMock()

    results = await execute_batch_action(request, background_tasks, db_session)

    assert results["failed"] == 1
    assert "Video 999 not found" in results["errors"]
