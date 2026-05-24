from __future__ import annotations

from typing import Any, Dict

from app.common.responses import bad_request
from app.modules.hostel.services.base_service import BaseHostelService, service_logger


class HostelComplaintService(BaseHostelService):
    async def create_complaint(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data.get("description") or not data.get("category"):
            bad_request(message="category and description are required.")

        data["ticket_id"] = await self.sequence.simple("complaint", prefix="TKT")
        data.setdefault("status", "Pending")
        data.setdefault("urgency", "Medium")
        service_logger.info(
            "Creating complaint org=%s user=%s ticket_id=%s",
            self.ctx.org_id,
            self.ctx.user_id,
            data["ticket_id"],
        )
        return await self.repositories.complaints.create(data)

    async def list_complaints(self, skip: int, limit: int) -> Dict[str, Any]:
        documents = await self.repositories.complaints.list(
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        return {"documents": documents, "total": await self.repositories.complaints.total()}

