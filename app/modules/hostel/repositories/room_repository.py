from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.hostel.entities.room import ROOM
from app.modules.hostel.repositories.base import HostelEntityRepository


class RoomRepository(HostelEntityRepository):
    entity = ROOM

    async def find_by_number(self, room_number: str) -> Optional[Dict[str, Any]]:
        return await self.find_entity({"data.roomNumber": room_number})

    async def find_in_building(
        self,
        building_id: str,
        room_number: str,
    ) -> Optional[Dict[str, Any]]:
        return await self.find_entity(
            {
                "data.building_id": building_id,
                "data.roomNumber": room_number,
            }
        )

    async def find_by_building_and_number(
        self,
        building_identifier: str,
        room_number: str,
    ) -> Optional[Dict[str, Any]]:
        return await self.find_entity(
            {
                "$or": [
                    {"data.building_id": building_identifier},
                    {"data.buildingName": building_identifier},
                ],
                "data.roomNumber": room_number,
            }
        )

    async def update_by_number(
        self,
        room_number: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return await self.update_entity({"data.roomNumber": room_number}, data)

