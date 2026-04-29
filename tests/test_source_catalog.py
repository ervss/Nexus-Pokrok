import pytest
from app.source_catalog import normalize_search_source_key, filter_valid_discovery_sources

@pytest.mark.parametrize("raw, expected", [
    (None, None),
    ("", None),
    ("  ", None),
    ("all", None),
    ("*", None),
    ("any", None),
    ("pornhub", "pornhub"),
    ("xvideos", "xvideos"),
    ("ph", "pornhub"),
    ("xb", "xvideos"),
    ("coomer", "kemono"),
    ("pornhub.com", "pornhub"),
    ("kemono.party", "kemono"),
    ("pornhub.net", "pornhub"),
    ("xvideos.black", "xvideos"),
    ("  PH  ", "pornhub"),
    ("PornHub", "pornhub"),
    ("unknown", None),
    ("unknown.com", None),
])
def test_normalize_search_source_key(raw, expected):
    assert normalize_search_source_key(raw) == expected

def test_filter_valid_discovery_sources():
    assert filter_valid_discovery_sources([]) == []
    assert filter_valid_discovery_sources(None) == []

    raw_list = ["ph", "invalid", "pornhub", None, "xb", "xvideos.com", "  ", "all"]
    # ph -> pornhub
    # invalid -> None
    # pornhub -> pornhub (duplicate)
    # None -> skip
    # xb -> xvideos
    # xvideos.com -> xvideos (duplicate)
    # "  " -> None
    # "all" -> None

    expected = ["pornhub", "xvideos"]
    assert filter_valid_discovery_sources(raw_list) == expected
