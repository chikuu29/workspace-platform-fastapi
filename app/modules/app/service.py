import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import UploadFile
from app.core.config import settings
from app.modules.app.repository import AppRepository
from app.core.logger import create_logger

class AppService:
    def __init__(self, repository: AppRepository):
        self.repository = repository
        self.logger = create_logger("app_service")

    def _create_upload_name(self, original_name: str) -> str:
        original_path = Path(original_name)
        suffix = original_path.suffix
        stem = original_path.stem or "file"
        return f"{int(time.time() * 1000)}-{stem}{suffix}"

    async def get_templates(self, query: Dict[str, Any]) -> List[Any]:
        self.logger.debug(f"Fetching templates with query={query}")
        return await self.repository.get_templates(query)

    async def get_app_configuration(self) -> Optional[Dict[str, Any]]:
        self.logger.debug("Fetching app menu configuration")
        config_doc = await self.repository.get_menu_config()
        if config_doc:
            return config_doc.get("config")
        self.logger.warning("Menu configuration not found in DB")
        return None

    def get_notifications(self) -> List[Dict[str, Any]]:
        return [
            {"id": 1, "info": "You have a new message", "aName": "Alice"},
            {"id": 2, "info": "Class starts at 6 PM", "aName": "Gym"},
        ]

    async def get_database_statistics(self) -> Dict[str, Any]:
        return await self.repository.get_db_stats()

    async def upload_files(
        self, 
        files: List[UploadFile], 
        app_name: str, 
        current_user: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        
        self.logger.info(f"Processing upload of {len(files)} files for app {app_name}")
        storage_directory = settings.STORAGE_ROOT / app_name
        storage_directory.mkdir(parents=True, exist_ok=True)

        file_details = []
        for upload in files[:10]:
            file_name = self._create_upload_name(upload.filename)
            destination = storage_directory / file_name
            content = await upload.read()
            destination.write_bytes(content)

            file_details.append(
                {
                    "filename": file_name,
                    "originalName": upload.filename,
                    "size": len(content),
                    "mimeType": upload.content_type,
                    "absolutePath": str(destination),
                    "accessObjectPath": f"public/storage/{app_name}/{file_name}",
                    "accessUrl": f"{settings.FILE_UPLOAD_URL.rstrip('/')}/{app_name}/{file_name}",
                }
            )

        if file_details:
            self.logger.debug(f"Saving upload details to DB for {len(file_details)} files")
            await self.repository.save_upload_details(
                {
                    "uploadFiles": file_details,
                    "appName": app_name,
                    **current_user,
                }
            )

        self.logger.info("File upload processing complete")
        return file_details
