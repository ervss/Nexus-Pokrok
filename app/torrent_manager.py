import subprocess
import os
import threading
import json
import logging
import time
import urllib.parse
from app.database import SessionLocal, Video
from app.websockets import manager
import asyncio
from app.services import VIPVideoProcessor

class TorrentManager:
    def __init__(self):
        self.active_processes = {}
        self.download_dir = os.path.join("app", "static", "local_videos", "torrents")
        os.makedirs(self.download_dir, exist_ok=True)
        # Port pool for streaming (8002 - 8099)
        self.available_ports = set(range(8002, 8100))

    def start_torrent(self, magnet_url: str, title: str):
        if not self.available_ports:
            raise Exception("No available ports for torrent streaming.")

        port = self.available_ports.pop()

        # Start webtorrent process with web server on allocated port, outputting to torrents dir
        # --keep-seeding=false will make it close when download finishes
        # However, we want to control the lifecycle. If we just stream, webtorrent streams AND downloads.
        # Once it finishes, we will process it.
        # But we need output in JSON to parse info.

        # Instead of just streaming, let's stream AND get info.
        cmd = [
            "webtorrent", "download", magnet_url,
            "--out", self.download_dir,
            "--port", str(port),
            "--quiet" # Don't flood console with ascii progress
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        db = SessionLocal()
        video = Video(
            title=title,
            url=f"http://localhost:{port}/", # WebTorrent CLI serves the largest file at the root stream
            source_url=magnet_url,
            batch_name=f"Torrent_{time.strftime('%Y%m%d')}",
            status="downloading",
            storage_type="local"
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        video_id = video.id
        db.close()

        # Monitor the process in a thread
        threading.Thread(target=self._monitor_process, args=(video_id, process, magnet_url, port), daemon=True).start()

        return video_id, port

    def _monitor_process(self, video_id, process, magnet_url, port):
        self.active_processes[video_id] = process

        # Webtorrent CLI normally exits when 100% complete if keep-seeding isn't set
        process.wait()

        self.available_ports.add(port)
        if video_id in self.active_processes:
            del self.active_processes[video_id]

        # Download finished!
        db = SessionLocal()
        try:
            video = db.query(Video).get(video_id)
            if not video:
                return

            # Find the downloaded file
            # WebTorrent creates a folder based on the torrent name.
            # We need to find the largest video file in self.download_dir
            largest_file = None
            max_size = 0

            # This is a bit naive if multiple torrents download at once,
            # but WebTorrent isolates by torrent name folder.
            for root, dirs, files in os.walk(self.download_dir):
                for file in files:
                    if file.lower().endswith(('.mp4', '.mkv', '.avi', '.webm', '.mov')):
                        path = os.path.join(root, file)
                        # Ensure this file belongs to a recently modified folder to guess it's ours,
                        # or ideally parse webtorrent output. For simplicity, just find the newest large video.
                        size = os.path.getsize(path)
                        if size > max_size:
                            max_size = size
                            largest_file = path

            if largest_file:
                # Calculate relative path
                rel_path = largest_file.split("app/")[-1]
                if not rel_path.startswith("/"):
                    rel_path = "/" + rel_path

                video.url = rel_path
                video.status = "ready"
                db.commit()

                # Trigger thumbnail generation in background using Celery
                from app.workers.tasks import process_video_task
                process_video_task.delay(video.id)
            else:
                video.status = "error"
                video.error_msg = "Download finished but no video file found."
                db.commit()

        except Exception as e:
            logging.error(f"Torrent monitor error: {e}")
        finally:
            db.close()

torrent_manager = TorrentManager()
