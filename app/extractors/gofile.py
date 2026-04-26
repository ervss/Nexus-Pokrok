"""
GoFile.io video extractor for direct streaming.
Uses official GoFile API to extract metadata and stream URLs.
Supports both single files and folder URLs with multiple videos.
"""
import requests
from .base import VideoExtractor
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class GoFileExtractor(VideoExtractor):
    """
    Extracts video metadata and stream URLs from GoFile.io links.
    Supports direct streaming without downloading.
    Handles both single file and folder URLs.
    """

    @property
    def name(self) -> str:
        return "GoFile"

    def can_handle(self, url: str) -> bool:
        return "gofile.io" in url.lower()

    _cached_token = None  # Cache token for session
    _user_token = None  # User's permanent account token (optional)

    @staticmethod
    def set_user_token(token: str):
        """
        Set a user's permanent GoFile account token.
        This allows access to private/premium folders.

        Args:
            token: User's GoFile account token from their profile
        """
        GoFileExtractor._user_token = token
        logger.info("GoFile user token configured")

    @staticmethod
    def _get_token() -> Optional[str]:
        """
        Get GoFile API token.
        Priority: 1) User token, 2) Cached guest token, 3) Create new guest token

        Returns:
            API token string or None if failed
        """
        # Use user token if available (for private folders)
        if GoFileExtractor._user_token:
            return GoFileExtractor._user_token

        # Use cached guest token
        if GoFileExtractor._cached_token:
            return GoFileExtractor._cached_token

        # Create new guest token
        try:
            response = requests.post('https://api.gofile.io/accounts', timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok':
                    token = data.get('data', {}).get('token')
                    if token:
                        GoFileExtractor._cached_token = token
                        logger.info("Successfully obtained GoFile guest token")
                        return token
        except Exception as e:
            logger.error(f"Failed to get GoFile token: {e}")

        return None

    @staticmethod
    def can_handle(url: str) -> bool:
        """
        Check if URL is a GoFile link.

        Args:
            url: URL to check

        Returns:
            True if URL contains gofile.io/d/
        """
        return 'gofile.io/d/' in url.lower()

    @staticmethod
    def extract_multiple(url: str) -> List[Dict[str, any]]:
        """
        Extract all video files from a GoFile folder URL.

        Args:
            url: GoFile URL (https://gofile.io/d/{folderId})

        Returns:
            List of dictionaries with video metadata for each video found
        """
        try:
            # Get authentication token
            token = GoFileExtractor._get_token()
            if not token:
                logger.error("Failed to obtain GoFile API token")
                return []

            # Extract folderId from URL
            folder_id = url.split('/d/')[-1].split('?')[0].strip()

            if not folder_id:
                logger.error("Failed to extract folderId from GoFile URL")
                return []

            # Call GoFile API with token as query parameter
            api_url = f"https://api.gofile.io/contents/{folder_id}?token={token}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }

            logger.info(f"Fetching GoFile folder metadata for: {folder_id}")
            response = requests.get(api_url, headers=headers, timeout=10)

            if response.status_code != 200:
                logger.error(f"GoFile API returned status {response.status_code}")
                return []

            data = response.json()

            # Check API response status
            status = data.get('status')
            if status != 'ok':
                if status == 'error-notPremium':
                    logger.warning(f"GoFile folder {folder_id} requires premium account (private/password-protected)")
                elif status == 'error-notFound':
                    logger.warning(f"GoFile folder {folder_id} not found (expired or invalid)")
                else:
                    logger.error(f"GoFile API error: {status}")
                return []

            # Extract content data
            content_data = data.get('data', {})
            contents = content_data.get('contents', {})

            # Extract all video files
            videos = []
            for content_id, content_info in contents.items():
                if content_info.get('type') == 'file':
                    name = content_info.get('name', '')

                    # Check if it's a video file
                    if any(ext in name.lower() for ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8']):
                        stream_url = content_info.get('link') or content_info.get('directLink') or content_info.get('downloadLink')

                        if stream_url:
                            video_data = {
                                'title': name,
                                'stream_url': stream_url,
                                'thumbnail': 'https://gofile.io/dist/img/logo.png',
                                'duration': 0,
                                'source_url': url,
                                'width': 0,
                                'height': 0,
                                'filesize': content_info.get('size', 0)
                            }
                            videos.append(video_data)
                            logger.info(f"Found video in folder: {name}")

            logger.info(f"Successfully extracted {len(videos)} videos from GoFile folder")
            return videos

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error while fetching GoFile folder: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting GoFile folder metadata: {e}", exc_info=True)
            return []

    async def extract(self, url: str) -> Optional[Dict[str, any]]:
        """
        Extract video metadata from GoFile URL.
        For single files or fallback, use extract_multiple() for folders.

        Args:
            url: GoFile URL (https://gofile.io/d/{fileId})

        Returns:
            Dictionary with video metadata:
            - title: Video filename
            - stream_url: Direct stream URL
            - thumbnail: Thumbnail URL (fallback to GoFile logo)
            - duration: Duration (N/A for GoFile)
            - source_url: Original GoFile URL
        """
        try:
            # Get authentication token
            token = GoFileExtractor._get_token()
            if not token:
                logger.error("Failed to obtain GoFile API token")
                return None

            # Extract fileId from URL
            # URL format: https://gofile.io/d/{fileId}
            file_id = url.split('/d/')[-1].split('?')[0].strip()

            if not file_id:
                logger.error("Failed to extract fileId from GoFile URL")
                return None

            # Call GoFile API with token as query parameter
            api_url = f"https://api.gofile.io/contents/{file_id}?token={token}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }

            logger.info(f"Fetching GoFile metadata for: {file_id}")
            response = requests.get(api_url, headers=headers, timeout=10)

            if response.status_code != 200:
                logger.error(f"GoFile API returned status {response.status_code}")
                return None

            data = response.json()

            # Check API response status
            status = data.get('status')
            if status != 'ok':
                if status == 'error-notPremium':
                    logger.warning(f"GoFile content {file_id} requires premium account")
                elif status == 'error-notFound':
                    logger.warning(f"GoFile content {file_id} not found")
                else:
                    logger.error(f"GoFile API error: {status}")
                return None

            # Extract content data
            content_data = data.get('data', {})

            # GoFile API returns content info
            contents = content_data.get('contents', {})

            # Get first video file from contents
            video_file = None
            for content_id, content_info in contents.items():
                if content_info.get('type') == 'file':
                    # Check if it's a video file
                    name = content_info.get('name', '')
                    if any(ext in name.lower() for ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m3u8']):
                        video_file = content_info
                        break

            if not video_file:
                # If no video found in contents, try the main content
                video_file = content_data

            # Extract metadata
            title = video_file.get('name') or video_file.get('fileName') or f"GoFile_{file_id}"
            stream_url = video_file.get('link') or video_file.get('directLink') or video_file.get('downloadLink')

            if not stream_url:
                logger.error("No stream URL found in GoFile response")
                return None

            # Build result
            result = {
                'id': file_id,
                'title': title,
                'description': f"GoFile upload: {title}",
                'thumbnail': 'https://gofile.io/dist/img/logo.png',  # GoFile logo fallback
                'duration': 0,  # GoFile doesn't provide duration
                'stream_url': stream_url,
                'width': 0,
                'height': 0,
                'tags': [],
                'uploader': 'GoFile User',
                'is_hls': '.m3u8' in stream_url.lower()
            }

            logger.info(f"Successfully extracted GoFile: {title}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error while fetching GoFile: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting GoFile metadata: {e}", exc_info=True)
            return None
