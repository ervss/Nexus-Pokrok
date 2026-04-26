
from telethon import TelegramClient
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

class TelegramAuthManager:
    def __init__(self):
        self.client = None
        self.phone = None
        self.phone_code_hash = None
        self.is_connected = False

    async def get_client(self, api_id=None, api_hash=None):
        if self.client and self.client.is_connected():
            return self.client
            
        session_file = 'telegram_session.session'
        
        # Priority: Args > Env > Default/Error
        
        # Clean api_id: if it's not a digit string, ignore it (likely garbage from UI)
        if api_id and not str(api_id).isdigit():
            api_id = None
            
        real_id = api_id or os.getenv('TELEGRAM_API_ID')
        real_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        
        if not real_id or not str(real_id).isdigit():
            # Try reloading env
            load_dotenv()
            real_id = os.getenv('TELEGRAM_API_ID')
            real_hash = os.getenv('TELEGRAM_API_HASH')

        if not real_id or not real_hash:
             raise ValueError(f"API ID and Hash are required. Got ID: {real_id}")

        self.client = TelegramClient(session_file, int(real_id), real_hash)
        await self.client.connect()
        return self.client

    async def send_code(self, api_id, api_hash, phone):
        client = await self.get_client(api_id, api_hash)
        
        if not await client.is_user_authorized():
            self.phone = phone
            res = await client.send_code_request(phone)
            self.phone_code_hash = res.phone_code_hash
            return {"status": "code_sent", "message": "Code sent to your other Telegram device."}
        else:
            return {"status": "already_logged_in", "message": "Already logged in."}

    async def verify_code(self, code, password=None):
        if not self.client:
            raise ValueError("Client not initialized. Send code first.")
        
        try:
            await self.client.sign_in(phone=self.phone, code=code, phone_code_hash=self.phone_code_hash)
        except Exception as e:
            if "password" in str(e).lower() and password:
                await self.client.sign_in(password=password)
            elif "password" in str(e).lower():
                return {"status": "2fa_required", "message": "2FA Password required."}
            else:
                raise e
                
        # Save credentials to .env if successful
        self._save_creds(self.client.api_id, self.client.api_hash)
        return {"status": "success", "message": "Successfully logged in!"}
        
    async def verify_password(self, password):
         if not self.client: raise ValueError("Client not initialized.")
         await self.client.sign_in(password=password)
         self._save_creds(self.client.api_id, self.client.api_hash)
         return {"status": "success", "message": "Successfully logged in!"}

    def _save_creds(self, api_id, api_hash):
        # Allow persisting these for future restarts
        try:
            # Read existing
            lines = []
            if os.path.exists('.env'):
                with open('.env', 'r') as f: lines = f.readlines()
            
            # Filter out old
            lines = [l for l in lines if not l.startswith('TELEGRAM_API_')]
            
            # Append new
            lines.append(f"\nTELEGRAM_API_ID={api_id}\n")
            lines.append(f"TELEGRAM_API_HASH={api_hash}\n")
            
            with open('.env', 'w') as f:
                f.writelines(lines)
        except:
            pass

    async def content_status(self):
        if os.path.exists('telegram_session.session'):
             # Try to connect check
             try:
                 # We don't need real args here just to check file presence roughly, 
                 # but to strictly check validity we need a client.
                 # For UI speed we just return true if file exists for now.
                 return True
             except:
                 return False
        return False

manager = TelegramAuthManager()
