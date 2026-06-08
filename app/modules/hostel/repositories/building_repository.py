from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.hostel.entities.building import BUILDING
from app.modules.hostel.repositories.base import HostelEntityRepository


class BuildingRepository(HostelEntityRepository):
    entity = BUILDING

    async def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return await self.find_entity({"data.name": name})

    async def find_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        return await self.find_entity(
            {
                "$or": [
                    {"_meta.id": identifier},
                    {"data.name": identifier},
                ]
            }
        )

