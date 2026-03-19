from typing import Any, Dict, Optional
from app.common.repository import BaseRepository

class BaseService:
    """
    Generic Base Service for common business logic, communicating with a repository.
    """
    def __init__(self, repository: BaseRepository):
        self.repository = repository

    async def create_record(self, data: Dict[str, Any]) -> str:
        """Handles business logic before creating a record."""
        # Add common metadata (e.g., createdAt, is_active) here if needed globally
        return await self.repository.create(data)

    async def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        return await self.repository.get_by_id(record_id)
