from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple

class VideoExtractor(ABC):
    """
    Abstract base class for all site-specific extractors.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the extractor (e.g. 'Eporner', 'XVideos')"""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Returns True if this extractor can handle the given URL."""
        pass

    @abstractmethod
    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extracts metadata and stream URL.
        Returns a dictionary or None if extraction failed.
        
        Expected Return Shape:
        {
            "id": str,          # Source ID
            "title": str,
            "description": str,
            "thumbnail": str,
            "duration": int,    # Seconds
            "stream_url": str,  # Direct playable URL (mp4/m3u8)
            "width": int,
            "height": int,
            "tags": list,
            "uploader": str,
            "is_hls": bool
        }
        """
        pass
