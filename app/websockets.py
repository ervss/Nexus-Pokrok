
from typing import List
import json
import time
import asyncio
from fastapi import WebSocket
import redis.asyncio as redis
import os

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.pubsub_channel = "quantum_ws_events"
        self.redis = None
        self.pubsub_task = None

    async def start_pubsub(self):
        self.redis = redis.from_url(self.redis_url)
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.pubsub_channel)

        async def reader():
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        await self._local_broadcast(data)
            except Exception as e:
                print(f"PubSub reader error: {e}")

        self.pubsub_task = asyncio.create_task(reader())

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def _local_broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

    async def broadcast(self, message: str):
        # Publish to Redis so all workers/FastAPI instances get it
        if not self.redis:
            self.redis = redis.from_url(self.redis_url)
        await self.redis.publish(self.pubsub_channel, message)

    async def log(self, message: str, level: str = 'info'):
        """Broadcasts a log message to the frontend console."""
        payload = json.dumps({
            "type": "log",
            "message": message,
            "level": level,  # info, success, warning, error, working
            "timestamp": time.time()
        })
        await self.broadcast(payload)

    async def pulse(self):
        """Sends a minimal heartbeat to keep connections alive."""
        await self.broadcast(json.dumps({"type": "pulse", "timestamp": time.time()}))

manager = ConnectionManager()
