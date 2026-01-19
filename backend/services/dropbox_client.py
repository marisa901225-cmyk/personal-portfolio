
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class DropboxService:
    @staticmethod
    def get_access_token(app_key: str, app_secret: str, refresh_token: str) -> Optional[str]:
        """
        Refresh Token을 사용하여 일회성 Access Token을 발급받습니다.
        """
        logger.info("Refreshing Dropbox access token...")
        try:
            url = "https://api.dropbox.com/oauth2/token"
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            # Basic Auth 처리
            auth = (app_key, app_secret)
            response = requests.post(url, data=data, auth=auth, timeout=10)
            response.raise_for_status()
            return response.json().get("access_token")
        except Exception as e:
            logger.error(f"Failed to refresh Dropbox token: {e}")
            return None

    @staticmethod
    def upload_file(file_path: str, dropbox_path: str, access_token: str) -> bool:
        """
        파일을 드롭박스에 업로드합니다.
        """
        logger.info(f"Uploading {file_path} to Dropbox: {dropbox_path}")
        try:
            url = "https://content.dropboxapi.com/2/files/upload"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "add", "autorename": true, "mute": false}}',
                "Content-Type": "application/octet-stream",
            }
            with open(file_path, "rb") as f:
                response = requests.post(url, headers=headers, data=f, timeout=300) # 대용량 고려 5분
            
            if response.status_code == 200:
                logger.info("Dropbox upload success.")
                return True
            else:
                logger.error(f"Dropbox upload failed: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error during Dropbox upload: {e}")
            return False
