import requests
import os
import logging
try:
    from mega import Mega
except Exception:
    Mega = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GofileExtractor:
    def __init__(self):
        self.api_base = "https://api.gofile.io"
        self.token = self._get_guest_token()

    def _get_guest_token(self):
        """
        Gofile requires a guest token for unauthenticated API requests.
        """
        try:
            response = requests.post(f"{self.api_base}/accounts", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data['status'] == 'ok':
                return data['data']['token']
        except Exception as e:
            logger.error(f"Error getting Gofile guest token: {e}")
        return None

    def get_content(self, content_id):
        """
        Recursively fetches file info from Gofile.
        """
        if not self.token:
            self.token = self._get_guest_token()
            
        url = f"{self.api_base}/contents/{content_id}"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            if data['status'] != 'ok':
                logger.error(f"Gofile API error: {data.get('status')}")
                return []
            
            files = []
            content_data = data['data']
            
            # If it's a folder, traverse children
            if content_data['type'] == 'folder':
                for child_id, child_info in content_data.get('children', {}).items():
                    if child_info['type'] == 'file':
                        files.append({
                            "name": child_info['name'],
                            "link": child_info['link'],
                            "size": child_info['size'],
                            "mimetype": child_info['mimetype'],
                            "thumbnail": child_info.get('thumbnail')
                        })
                    elif child_info['type'] == 'folder':
                        files.extend(self.get_content(child_id))
            else:
                # Single file
                files.append({
                    "name": content_data['name'],
                    "link": content_data['link'],
                    "size": content_data['size'],
                    "mimetype": content_data['mimetype'],
                    "thumbnail": content_data.get('thumbnail')
                })
                
            return files
        except Exception as e:
            logger.error(f"Error fetching Gofile content: {e}")
            return []

class MegaExtractor:
    def __init__(self):
        if Mega is None:
            raise RuntimeError("Mega client is unavailable in this environment")
        self.mega = Mega()

    def get_info(self, url):
        """
        Retrieves file/folder info from Mega.nz.
        """
        try:
            # Using mega.py features to handle URLs
            # Note: handle quota limits gracefully in download logic
            info = self.mega.get_public_url_info(url)
            return info
        except Exception as e:
            logger.error(f"Error fetching Mega info: {e}")
            return None

class PixeldrainExtractor:
    def __init__(self):
        self.api_base = "https://pixeldrain.com/api"

    def get_file_info(self, file_id_or_url):
        """
        Gets file info from Pixeldrain API. Can accept ID or full URL.
        """
        import re
        file_id = file_id_or_url
        if 'pixeldrain.com' in file_id_or_url:
            match = re.search(r'/(?:u|l|file)/([a-zA-Z0-9]+)', file_id_or_url)
            if match:
                file_id = match.group(1)
            else:
                return None

        url = f"{self.api_base}/file/{file_id}/info"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                "name": data.get("name"),
                "size": data.get("size"),
                "link": f"https://pixeldrain.com/api/file/{file_id}",
                "thumbnail": f"https://pixeldrain.com/api/file/{file_id}/thumbnail"
            }
        except Exception as e:
            logger.error(f"Error fetching Pixeldrain info: {e}")
            return None

if __name__ == "__main__":
    # Example usage
    # gofile = GofileExtractor()
    # print(gofile.get_content("XXXXX"))
    pass
