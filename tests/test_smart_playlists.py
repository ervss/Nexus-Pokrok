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
