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
from app.source_catalog import (
    normalize_search_source_key,
    filter_valid_discovery_sources,
    classify_library_source_name,
    unknown_domain_from_urls,
)

def test_normalize_search_source_key():
    # Basic canonical keys
    assert normalize_search_source_key("erome") == "erome"
    assert normalize_search_source_key("xvideos") == "xvideos"

    # Aliases
    assert normalize_search_source_key("ph") == "pornhub"
    assert normalize_search_source_key("coomer") == "kemono"

    # Suffixes
    assert normalize_search_source_key("pornhub.com") == "pornhub"
    assert normalize_search_source_key("xvideos.red") == "xvideos"
    assert normalize_search_source_key("kemono.su") == "kemono"

    # Special values (should return None)
    assert normalize_search_source_key("all") is None
    assert normalize_search_source_key("*") is None
    assert normalize_search_source_key("any") is None
    assert normalize_search_source_key(None) is None
    assert normalize_search_source_key("") is None
    assert normalize_search_source_key("   ") is None

    # Unknown
    assert normalize_search_source_key("unknown_site") is None

    # Mixed case and whitespace
    assert normalize_search_source_key("  EROME  ") == "erome"
    assert normalize_search_source_key("PORNHUB.COM") == "pornhub"

def test_filter_valid_discovery_sources():
    # Empty/None
    assert filter_valid_discovery_sources(None) == []
    assert filter_valid_discovery_sources([]) == []

    # mixed list
    raw = ["erome", None, "ph", "unknown", "  xvideos.red  ", "erome"]
    # expected: ["erome", "pornhub", "xvideos"]
    # "erome" is duplicated, should be deduplicated
    # None is skipped
    # "ph" -> "pornhub"
    # "unknown" -> None (skipped)
    # "  xvideos.red  " -> "xvideos"
    assert filter_valid_discovery_sources(raw) == ["erome", "pornhub", "xvideos"]

def test_classify_library_source_name():
    # Happy paths
    assert classify_library_source_name("https://www.eporner.com/video-123") == "Eporner"
    assert classify_library_source_name("https://xvideos.red/video-456") == "XVideos"

    # source_url priority
    assert classify_library_source_name(url="https://unknown.com", source_url="https://pornhub.com/view_video.php?viewkey=1") == "Pornhub"

    # Case insensitivity
    assert classify_library_source_name("HTTPS://EROME.COM/A/BCDE") == "Erome"

    # Fallback to url
    assert classify_library_source_name(url="https://spankbang.com/video", source_url=None) == "SpankBang"

    # Unknown
    assert classify_library_source_name("https://google.com") == "Unknown"
    assert classify_library_source_name(None, None) == "Unknown"

def test_unknown_domain_from_urls():
    # Known source (should return None)
    assert unknown_domain_from_urls("https://pornhub.com/video") is None

    # Unknown source (should return domain)
    assert unknown_domain_from_urls("https://some-weird-site.org/video") == "some-weird-site.org"

    # www. stripping
    assert unknown_domain_from_urls("https://www.newsite.com/video") == "newsite.com"

    # source_url priority for unknown
    assert unknown_domain_from_urls(url="https://a.com", source_url="https://b.com") == "b.com"

    # Invalid URLs or non-http
    assert unknown_domain_from_urls("not a url") is None
    assert unknown_domain_from_urls("ftp://files.com") is None
    assert unknown_domain_from_urls(None) is None
