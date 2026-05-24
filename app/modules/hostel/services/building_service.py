from __future__ import annotations

from typing import Any, Dict, List

from app.common.responses import bad_request, conflict
from app.modules.hostel.services.base_service import BaseHostelService, service_logger


class HostelBuildingService(BaseHostelService):
    async def add_building(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data.get("name"):
            bad_request(message="name is required.")

        existing = await self.repositories.buildings.find_by_name(data["name"])
        if existing:
            conflict(
                message=f"Building '{data['name']}' already exists.",
                error_code="DUPLICATE_BUILDING",
            )

        service_logger.info("Adding building org=%s user=%s", self.ctx.org_id, self.ctx.user_id)
        return await self.repositories.buildings.create(data)

    async def list_buildings(self, skip: int, limit: int) -> Dict[str, Any]:
        documents = await self.repositories.buildings.list(
            sort=[("data.name", 1)],
            skip=skip,
            limit=limit,
        )
        return {"documents": documents, "total": await self.repositories.buildings.total()}

    async def building_options(self) -> List[Dict[str, Any]]:
        documents = await self.repositories.buildings.list(sort=[("data.name", 1)])
        options = []
        for doc in documents:
            name = doc["data"].get("name", "Unnamed Building")
            location = doc["data"].get("location", "")
            options.append(
                {
                    "id": doc["_meta"]["record_id"],
                    "name": f"{name} ({location})" if location else name,
                }
            )
        return options

