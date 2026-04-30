import pytest
from app.source_catalog import normalize_search_source_key, filter_valid_discovery_sources

def test_normalize_search_source_key():
    # None input
    assert normalize_search_source_key(None) is None

    # Empty or special strings
    assert normalize_search_source_key("") is None
    assert normalize_search_source_key("  ") is None
    assert normalize_search_source_key("all") is None
    assert normalize_search_source_key("*") is None
    assert normalize_search_source_key("any") is None

    # Canonical key
    assert normalize_search_source_key("pornhub") == "pornhub"

    # Alias
    assert normalize_search_source_key("ph") == "pornhub"
    assert normalize_search_source_key("coomer") == "kemono"

    # Alias with suffix
    assert normalize_search_source_key("pornhub.com") == "pornhub"

    # Key with suffix NOT in aliases but base is canonical
    # .red is in the allowed suffixes and 'bunkr' is in DISCOVERY_SEARCH_SOURCE_KEYS
    assert normalize_search_source_key("bunkr.red") == "bunkr"

    # Key with suffix NOT in aliases and base NOT canonical
    assert normalize_search_source_key("unknown.com") is None

    # Case and whitespace
    assert normalize_search_source_key("  PornHub  ") == "pornhub"

    # Unknown key
    assert normalize_search_source_key("random") is None

def test_filter_valid_discovery_sources():
    # None or empty
    assert filter_valid_discovery_sources(None) == []
    assert filter_valid_discovery_sources([]) == []

    # List with None
    assert filter_valid_discovery_sources([None, "pornhub"]) == ["pornhub"]

    # Mixed valid/invalid
    assert filter_valid_discovery_sources(["pornhub", "unknown", "ph"]) == ["pornhub"]

    # Deduplication
    assert filter_valid_discovery_sources(["pornhub", "ph", "  PORNHUB  "]) == ["pornhub"]
