
from typing import List
import json
import time
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # Iterate over a copy to allow safe removal during iteration
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except:
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

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
