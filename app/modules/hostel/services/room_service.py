from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.common.responses import bad_request, conflict, not_found
from app.modules.hostel.entities.room import (
    capacity,
    normalize_room_defaults,
    occupancy_status,
    occupants,
    option_label,
    security_deposit,
)
from app.modules.hostel.services.base_service import BaseHostelService, service_logger


class HostelRoomService(BaseHostelService):
    async def add_room(self, data: Dict[str, Any]) -> Dict[str, Any]:
        building_id = data.get("building_id") or data.get("buildingName")
        if not building_id:
            bad_request(message="buildingName or building_id is required.")
        if not data.get("roomNumber"):
            bad_request(message="roomNumber is required.")

        building_doc = await self.repositories.buildings.find_by_identifier(building_id)
        if not building_doc:
            not_found(message=f"Building block '{building_id}' not found.")

        normalized_building_id = building_doc["_meta"]["id"]
        building_name = building_doc["data"].get("name", "Unnamed Building")
        existing = await self.repositories.rooms.find_in_building(
            normalized_building_id,
            data["roomNumber"],
        )
        if existing:
            conflict(
                message=f"Room '{data['roomNumber']}' already exists in building '{building_name}'.",
                error_code="DUPLICATE_ROOM",
            )

        data["building_id"] = normalized_building_id
        data["buildingName"] = building_name
        normalize_room_defaults(data)
        service_logger.info("Adding room org=%s user=%s", self.ctx.org_id, self.ctx.user_id)
        return await self.repositories.rooms.create(data)

    async def room_options(self, building_name: Optional[str]) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if building_name:
            query["$or"] = [
                {"data.building_id": building_name},
                {"data.buildingName": building_name},
            ]

        documents = await self.repositories.rooms.list(sort=[("data.roomNumber", 1)], query=query)
        options = []
        for doc in documents:
            room_data = doc["data"]
            if len(occupants(room_data)) < capacity(room_data):
                options.append({"id": room_data.get("roomNumber"), "name": option_label(room_data)})
        return options

    async def room_security_deposit(
        self,
        building_name: str,
        room_number: str,
    ) -> Dict[str, Any]:
        room = await self.repositories.rooms.find_by_building_and_number(
            building_name,
            room_number,
        )
        if not room:
            return {"securityDeposit": 0}

        room_data = room["data"]
        rent_amount = float(room_data.get("rentAmount") or 0.0)
        cap = capacity(room_data)
        deposit = security_deposit(room_data)
        return {
            "securityDeposit": deposit,
            "rentAmount": rent_amount,
            "securityDepositNote": (
                "Calculated as (rentAmount / capacity) * 2 Months = "
                f"({rent_amount} / {cap}) * 2"
            ),
        }

    async def list_rooms(self, skip: int, limit: int) -> Dict[str, Any]:
        documents = await self.repositories.rooms.list(
            sort=[("data.roomNumber", 1)],
            skip=skip,
            limit=limit,
        )
        for doc in documents:
            doc["data"]["status"] = occupancy_status(doc["data"])
        return {"documents": documents, "total": await self.repositories.rooms.total()}

