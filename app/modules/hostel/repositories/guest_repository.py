from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.hostel.entities.guest import GUEST
from app.modules.hostel.repositories.base import HostelEntityRepository


class GuestRepository(HostelEntityRepository):
    entity = GUEST

    async def find_by_guest_id(self, guest_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_entity(
            {
                "$or": [
                    {"data.guest_id": guest_id}
                ]
            }
        )

