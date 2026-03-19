from datetime import datetime, timezone
from typing import Dict, Any
from app.modules.gym.repository import GymRepository
from app.modules.gym.schemas import MemberCreatePayload
from app.core.logger import create_logger

class GymService:
    """
    Encapsulates core business logic for the Gym module.
    Tenant boundary is strictly respected by injecting a fully configured Repository.
    """
    def __init__(self, repository: GymRepository):
        self.repository = repository
        self.logger = create_logger("gym_service")

    async def add_member(
        self, 
        payload: MemberCreatePayload, 
        current_user: dict
    ) -> Dict[str, Any]:
        """
        Business logic for adding a member.
        """
        self.logger.info(f"Initiating new gym member addition by {current_user.get('email', 'unknown')}")
        
        document = {
            "recentData": payload.model_dump(),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "createdByEmail": current_user.get("email"),
            "clientDetails": current_user,
            "status": "active"
        }

        try:
            inserted_id = await self.repository.create(document)
            self.logger.info(f"Successfully added gym member with ID={inserted_id}")
            return {
                "inserted_id": inserted_id,
                "data": document
            }
        except Exception as e:
            self.logger.error(f"Failed to add gym member: {e}")
            raise
