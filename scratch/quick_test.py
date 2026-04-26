import asyncio
import sys
import os

# Add root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.extractors.filester import FilesterExtractor

async def test_filester():
    extractor = FilesterExtractor()
    test_url = "https://filester.net/v/79q2m04v5" # Example URL
    print(f"Testing Filester with {test_url}...")
    try:
        # Filester might require cookies or session, but let's see if it initializes
        # This will likely fail without a real URL, but we check if it imports and runs
        result = await extractor.extract(test_url)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_filester())
