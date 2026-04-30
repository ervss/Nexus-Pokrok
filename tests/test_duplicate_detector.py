import pytest
from app.duplicate_detector import hamming_distance

def test_hamming_distance_identical():
    """Test distance between identical hashes"""
    h = "a1b2c3d4e5f60718"
    assert hamming_distance(h, h) == 0

def test_hamming_distance_different():
    """Test distance between different hashes"""
    h1 = "0000000000000000"
    h2 = "0000000000000001" # 0001
    assert hamming_distance(h1, h2) == 1

    h3 = "0000000000000003" # 0011
    assert hamming_distance(h1, h3) == 2

    h4 = "ffffffffffffffff"
    assert hamming_distance(h1, h4) == 64

def test_hamming_distance_none_or_empty():
    """Test distance with None or empty inputs"""
    h = "a1b2c3d4e5f60718"
    assert hamming_distance(None, h) == 999
    assert hamming_distance(h, None) == 999
    assert hamming_distance(None, None) == 999
    assert hamming_distance("", h) == 999
    assert hamming_distance(h, "") == 999
    assert hamming_distance("", "") == 999

def test_hamming_distance_invalid_hex():
    """Test distance with invalid hex strings"""
    h = "a1b2c3d4e5f60718"
    # imagehash.hex_to_hash usually expects 16 chars for 64-bit phash
    # but it might handle others or throw depending on length/content
    assert hamming_distance("invalid", h) == 999
    assert hamming_distance(h, "xyz") == 999
