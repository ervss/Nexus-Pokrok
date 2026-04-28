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

        db = SessionLocal()
        video = Video(
            title=title,
            url=f"/stream_torrent/{port}/resolve", # Will be intercepted by proxy to find correct index
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

        # Create an isolated download directory for this specific torrent
        isolated_dir = os.path.join(self.download_dir, str(video_id))
        os.makedirs(isolated_dir, exist_ok=True)

        cmd = [
            "webtorrent", "download", magnet_url,
            "--out", isolated_dir,
            "--port", str(port)
            # Removed --quiet so we can parse output for 100% completion
        ]

        try:
            # We must use PIPE to read output and detect when download finishes
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
        except FileNotFoundError:
            self.available_ports.add(port)
            db = SessionLocal()
            v = db.query(Video).get(video_id)
            if v:
                v.status = "error"
                v.error_msg = "WebTorrent CLI not found on server."
                db.commit()
            db.close()
            raise Exception("WebTorrent CLI is not installed on the server. Please run: npm install -g webtorrent-cli")

        # Monitor the process in a thread
        threading.Thread(target=self._monitor_process, args=(video_id, process, isolated_dir, port), daemon=True).start()

        return video_id, port

    def _monitor_process(self, video_id, process, isolated_dir, port):
        self.active_processes[video_id] = process

        # Read stdout to detect when download hits 100%
        # WebTorrent format usually includes something like "100%    Downloading..." or "Downloaded"
        is_completed = False
        try:
            for line in iter(process.stdout.readline, ''):
                # Check for 100% completion indicator
                if "100%" in line or "Seeding" in line:
                    is_completed = True
                    break
        except Exception as e:
            logging.error(f"Error reading webtorrent output: {e}")

        # If we reached 100%, we must manually kill the process since --port keeps it alive indefinitely
        if is_completed:
            logging.info(f"Torrent {video_id} hit 100%, terminating webtorrent server.")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        else:
            process.wait()

        self.available_ports.add(port)
        if video_id in self.active_processes:
            del self.active_processes[video_id]

        db = SessionLocal()
        try:
            video = db.query(Video).get(video_id)
            if not video:
                return

            # Find the largest video file inside the ISOLATED directory
            largest_file = None
            max_size = 0

            for root, dirs, files in os.walk(isolated_dir):
                for file in files:
                    if file.lower().endswith(('.mp4', '.mkv', '.avi', '.webm', '.mov')):
                        path = os.path.join(root, file)
                        size = os.path.getsize(path)
                        if size > max_size:
                            max_size = size
                            largest_file = path

            if largest_file:
                # Safely calculate relative path
                try:
                    rel_path = os.path.relpath(largest_file, "app")
                    rel_path = "/" + rel_path.replace("\\", "/")
                except ValueError:
                    # Fallback if path manipulation fails
                    rel_path = "/" + largest_file.replace("\\", "/").split("/app/")[-1]

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
