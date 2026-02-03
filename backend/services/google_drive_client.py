
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class GoogleDriveService:
    @staticmethod
    def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
        """
        Refresh Token을 사용하여 OAuth2 Access Token을 발급받습니다.
        """
        logger.info("Refreshing Google Drive access token...")
        try:
            url = "https://oauth2.googleapis.com/token"
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            response = requests.post(url, data=data, timeout=10)
            response.raise_for_status()
            return response.json().get("access_token")
        except Exception as e:
            logger.error(f"Failed to refresh Google Drive token: {e}")
            return None

    @staticmethod
    def get_folder_id_by_name(folder_name: str, access_token: str) -> Optional[str]:
        """
        폴더 이름으로 구글 드라이브 폴더 ID를 조회합니다.
        """
        try:
            url = "https://www.googleapis.com/drive/v3/files"
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {
                "q": f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                "fields": "files(id, name)",
                "spaces": "drive"
            }
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            files = response.json().get("files", [])
            if files:
                return files[0].get("id")
            return None
        except Exception as e:
            logger.error(f"Failed to find folder: {e}")
            return None

    @staticmethod
    def create_folder(folder_name: str, access_token: str) -> Optional[str]:
        """
        구글 드라이브에 새로운 폴더를 생성합니다.
        """
        try:
            url = "https://www.googleapis.com/drive/v3/files"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            data = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            return response.json().get("id")
        except Exception as e:
            logger.error(f"Failed to create folder: {e}")
            return None

    @staticmethod
    def upload_file(file_path: str, drive_folder_id: Optional[str], access_token: str) -> bool:
        """
        파일을 구글 드라이브에 업로드합니다.
        """
        logger.info(f"Uploading {file_path} to Google Drive...")
        files = {} # finally에서 닫기 위해 미리 선언
        try:
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            # 메타데이터 설정 (파일명 등)
            import os
            file_metadata = {"name": os.path.basename(file_path)}
            if drive_folder_id:
                file_metadata["parents"] = [drive_folder_id]

            # Multipart 업로드 구성
            import json
            files = {
                'data': ('metadata', json.dumps(file_metadata), 'application/json; charset=UTF-8'),
                'file': open(file_path, 'rb')
            }

            response = requests.post(url, headers=headers, files=files, timeout=300)
            
            if response.status_code in [200, 201]:
                logger.info("Google Drive upload success.")
                return True
            else:
                logger.error(f"Google Drive upload failed: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error during Google Drive upload: {e}")
            return False
        finally:
            if 'file' in files:
                files['file'].close()
