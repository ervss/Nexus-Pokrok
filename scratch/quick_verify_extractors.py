import os
import sys
import asyncio
import traceback

# Add the project root to the path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.extractors.registry import ExtractorRegistry
from app.extractors import init_registry, register_extended_extractors

def run_checks():
    print("Initializing registry...")
    init_registry()
    register_extended_extractors()
    
    extractors = ExtractorRegistry.get_all()
    print(f"Total extractors registered: {len(extractors)}")
    
    success_count = 0
    fail_count = 0
    
    for ex in extractors:
        try:
            name = ex.name
            # Test can_handle with a dummy URL
            dummy_url = f"https://example.com/test_{name.lower()}"
            res = ex.can_handle(dummy_url)
            print(f"[OK] {name} loaded successfully (can_handle returned {res})")
            success_count += 1
        except Exception as e:
            print(f"[ERROR] {ex.__class__.__name__} failed basic checks:")
            traceback.print_exc()
            fail_count += 1
            
    print("-" * 40)
    print(f"Verification complete. OK: {success_count}, FAILED: {fail_count}")

if __name__ == "__main__":
    run_checks()
