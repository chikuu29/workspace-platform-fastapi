from __future__ import annotations

from typing import Any, Dict

from app.common.responses import bad_request, not_found
from app.modules.hostel.entities.guest import occupant_reference
from app.modules.hostel.entities.room import capacity, occupants
from app.modules.hostel.services.base_service import BaseHostelService, service_logger


class HostelGuestService(BaseHostelService):
    async def add_guest(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data.get("firstName") or not data.get("lastName"):
            bad_request(message="firstName and lastName are required.")

        room_doc = None
        room_number = data.get("room_number")
        if room_number:
            room_doc = await self.repositories.rooms.find_by_number(room_number)
            if not room_doc:
                not_found(message=f"Room '{room_number}' not found.")

            if len(occupants(room_doc["data"])) >= capacity(room_doc["data"]):
                bad_request(
                    message=f"Room '{room_number}' is already fully occupied.",
                    error_code="ROOM_FULL",
                )

        guest_id = await self.sequence.simple("guest", prefix="G")
        data["guest_id"] = guest_id
        data.setdefault("status", "Active")
        data.setdefault("rent_status", "Paid")

        guest_doc = await self.repositories.guests.create(data)

        if room_doc:
            current_occupants = occupants(room_doc["data"])
            current_occupants.append(occupant_reference(guest_id, guest_doc))
            room_update = {
                "occupants": current_occupants,
                "status": "Fully Occupied"
                if len(current_occupants) >= capacity(room_doc["data"])
                else "Partially Occupied",
            }
            await self.repositories.rooms.update_by_number(room_number, room_update)

        service_logger.info("Added guest org=%s user=%s", self.ctx.org_id, self.ctx.user_id)
        return guest_doc

    async def list_guests(self, skip: int, limit: int) -> Dict[str, Any]:
        documents = await self.repositories.guests.list(
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        for doc in documents:
            guest_id = doc["data"].get("guest_id") 
            unpaid = await self.repositories.invoices.total(
                {
                    "$or": [{"data.guest_id": guest_id}],
                    "data.status": {"$in": ["Unpaid", "Partially Paid"]},
                }
            )
            doc["data"]["rent_status"] = "Overdue" if unpaid > 0 else "Paid"
        return {"documents": documents, "total": await self.repositories.guests.total()}

