from __future__ import annotations

from typing import Any, Dict

from app.modules.hostel.entities.booking import INVOICE
from app.modules.hostel.entities.guest import full_name
from app.modules.hostel.entities.room import ROOM
from app.modules.hostel.services.base_service import BaseHostelService


class HostelAnalyticsService(BaseHostelService):
    async def kpis(self) -> Dict[str, Any]:
        repo = self.repositories.rooms
        room_pipeline = [
            {"$match": {**self.ctx.active_filter, **ROOM.query}},
            {
                "$project": {
                    "capacity": {"$toInt": {"$ifNull": ["$data.capacity", 1]}},
                    "occupants_count": {
                        "$cond": {
                            "if": {"$isArray": "$data.occupants"},
                            "then": {"$size": "$data.occupants"},
                            "else": 0,
                        }
                    },
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_beds": {"$sum": "$capacity"},
                    "occupied_beds": {"$sum": "$occupants_count"},
                }
            },
        ]
        room_result = await repo.collection.aggregate(room_pipeline).to_list(length=1)
        total_beds = room_result[0]["total_beds"] if room_result else 0
        occupied_beds = room_result[0]["occupied_beds"] if room_result else 0
        occupancy_rate = round((occupied_beds / total_beds * 100), 1) if total_beds else 0.0

        unpaid_pipeline = [
            {
                "$match": {
                    **self.ctx.active_filter,
                    **INVOICE.query,
                    "data.status": {"$in": ["Unpaid", "Partially Paid"]},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": {"$toDouble": {"$ifNull": ["$data.amount_due", 0.0]}}},
                }
            },
        ]
        unpaid_result = await repo.collection.aggregate(unpaid_pipeline).to_list(length=1)
        total_dues = unpaid_result[0]["total"] if unpaid_result else 0.0

        recent_docs = await self.repositories.guests.list(
            sort=[("_meta.created.at", -1)],
            limit=5,
        )
        recent_guests = [
            {
                "id": doc["_meta"]["id"],
                "name": full_name(doc["data"]),
                "room_number": doc["data"].get("room_number", "N/A"),
                "created_at": doc["_meta"]["created"]["at"],
            }
            for doc in recent_docs
        ]

        return {
            "kpis": {
                "total_beds": total_beds,
                "occupied_beds": occupied_beds,
                "occupancy_rate": f"{occupancy_rate}%",
                "active_tenants": await self.repositories.guests.total(),
                "total_dues": total_dues,
                "open_complaints": await self.repositories.complaints.total(
                    {"data.status": {"$ne": "Resolved"}}
                ),
                "total_buildings": await self.repositories.buildings.total(),
            },
            "recent_tenants": recent_guests,
        }

