from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.common.repository import BaseRepository

class OAuthRepository(BaseRepository):
    """
    Handles internal user database operations for OAuth authentication.
    """
    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "user"):
        super().__init__(db, collection_name)

    async def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email})

    async def update_user_oauth(self, user_id: str, oauth_snapshot: dict, image: Optional[str]) -> bool:
        return await self.update(user_id, {**oauth_snapshot, "image": image})

    async def create_oauth_user(self, user_doc: Dict[str, Any]) -> str:
        return await self.create(user_doc)
