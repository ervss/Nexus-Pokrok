from typing import List, Optional
from .base import VideoExtractor
import logging

class ExtractorRegistry:
    _extractors: List[VideoExtractor] = []

    @classmethod
    def register(cls, extractor: VideoExtractor):
        """Registers a new extractor instance."""
        cls._extractors.append(extractor)
        logging.info(f"Registered extractor: {extractor.name}")

    @classmethod
    def find_extractor(cls, url: str) -> Optional[VideoExtractor]:
        """Finds the first extractor that can handle the URL."""
        for extractor in cls._extractors:
            if extractor.can_handle(url):
                return extractor
        return None

    @classmethod
    def get_all(cls):
        return cls._extractors
