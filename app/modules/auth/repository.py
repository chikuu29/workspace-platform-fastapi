from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.common.repository import BaseRepository

class AuthRepository(BaseRepository):
    """
    Handles internal user database operations for authenticating.
    """
    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "user"):
        super().__init__(db, collection_name)

    async def find_user_by_login(self, login_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({
            "$or": [
                {"email": login_id},
                {"phone": login_id},
            ]
        })

    async def register_user(self, user_doc: Dict[str, Any]) -> str:
        return await self.create(user_doc)

    async def add_device_to_user(self, user_id: str, devices: List[Dict[str, Any]]) -> bool:
        return await self.update(user_id, {"devices": devices})
