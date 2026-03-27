from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Dict, Any, List, Optional

class AppRepository:
    """
    Handles database operations for the App module.
    Manages multiple domain collections: template, app_config, uploadFiles.
    """
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    @property
    def template_collection(self):
        return self.db["template"]

    @property
    def config_collection(self):
        return self.db["app_config"]

    @property
    def uploads_collection(self):
        return self.db["uploadFiles"]

    async def get_templates(self, query: dict) -> list:
        return await self.template_collection.find(query).to_list(length=None)

    async def get_menu_config(self) -> Optional[Dict[str, Any]]:
        return await self.config_collection.find_one({"type": "menu", "id": 1})

    async def get_db_stats(self) -> Dict[str, Any]:
        return await self.db.command("dbStats", scale=1024)

    async def save_upload_details(self, document: dict) -> str:
        result = await self.uploads_collection.insert_one(document)
        return str(result.inserted_id)
