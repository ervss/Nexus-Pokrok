import os
import requests
import ffmpeg
import logging
from urllib.parse import urlparse


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Archivist:
    def __init__(self, download_dir="./downloads"):
        self.download_dir = download_dir
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

    @staticmethod
    def sanitize_component(value: str, default: str = "General", max_len: int = 120) -> str:
        """Make a single path component safe on Windows/macOS/Linux.

        Prevents invalid Windows characters (e.g. ':'), strips trailing dots/spaces,
        collapses whitespace, and blocks path separators.
        """
        if value is None:
            value = ""
        value = str(value)
        value = value.replace("/", " ").replace("\\", " ")

        # Replace invalid characters across platforms / Windows.
        invalid = '<>:"|?*\x00'
        trans = {ord(ch): ord('_') for ch in invalid}
        value = value.translate(trans)

        # Remove control chars.
        value = "".join(ch for ch in value if ch >= " " )

        # Collapse whitespace.
        value = " ".join(value.split()).strip()

        # Windows disallows trailing dots/spaces.
        value = value.rstrip(" .")

        if not value:
            value = default

        # Avoid reserved device names on Windows.
        base = value.split(".", 1)[0].upper()
        if base in _WINDOWS_RESERVED_NAMES:
            value = f"_{value}"

        if max_len and len(value) > max_len:
            value = value[:max_len].rstrip(" .") or default

        return value

    @staticmethod
    def sanitize_filename(filename: str, default: str = "file") -> str:
        name = filename or ""
        root, ext = os.path.splitext(name)
        root = Archivist.sanitize_component(root, default=default, max_len=160)
        ext = ext.replace("/", "").replace("\\", "")
        if ext and any(ch in ext for ch in '<>:"|?*\x00'):
            ext = ""
        return f"{root}{ext}"

    async def download_file(self, url: str, source_site: str, album_name: str, filename: str):
        """
        Downloads a file or handles m3u8 stream.
        Saves to ./downloads/{Source_Site}/{Album_Name}/{Filename}.
        """
        safe_source = Archivist.sanitize_component(source_site, default="Source")
        safe_album = Archivist.sanitize_component(album_name, default="General")
        safe_filename = Archivist.sanitize_filename(filename, default="video")

        save_path = os.path.join(self.download_dir, safe_source, safe_album)
        os.makedirs(save_path, exist_ok=True)
            
        full_path = os.path.join(save_path, safe_filename)
        
        # Check if it's an m3u8 stream
        if url.endswith(".m3u8") or ".m3u8" in url:
            return await self._download_m3u8(url, full_path)
        else:
            return await self._download_direct(url, full_path)

    async def _download_direct(self, url: str, save_path: str):
        """
        Downloads a file directly using requests.
        """
        try:
            logger.info(f"Downloading direct link: {url}")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"Successfully downloaded to {save_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False

    async def _download_m3u8(self, url: str, save_path: str):
        """
        Uses ffmpeg to download and merge m3u8 streams.
        """
        # Ensure filename ends with .mp4
        if not save_path.endswith(".mp4"):
            save_path = os.path.splitext(save_path)[0] + ".mp4"
            
        try:
            logger.info(f"Downloading stream via ffmpeg: {url}")
            (
                ffmpeg
                .input(url)
                .output(save_path, c='copy', bsf='a=aac_adtstoasc')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logger.info(f"Successfully streamed to {save_path}")
            return True
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e.stderr.decode()}")
            return False
        except Exception as e:
            logger.error(f"Stream download failed: {e}")
            return False

if __name__ == "__main__":
    # Test
    # archivist = Archivist()
    # asyncio.run(archivist.download_file("http://example.com/video.mp4", "Test", "Album", "video.mp4"))
    pass
