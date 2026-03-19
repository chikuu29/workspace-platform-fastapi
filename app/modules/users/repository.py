from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.common.repository import BaseRepository

class UserRepository(BaseRepository):
    """
    Handles user database operations. Standardized on the 'user' collection.
    """
    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "user"):
        super().__init__(db, collection_name)

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"email": email})

    async def create_user(self, user_doc: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.collection.insert_one(user_doc)
        created = await self.collection.find_one({"_id": result.inserted_id})
        if created:
            created["id"] = str(created.pop("_id"))
        return created
