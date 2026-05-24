from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.hostel.entities.booking import COMPLAINT, INVOICE
from app.modules.hostel.repositories.base import HostelEntityRepository


class InvoiceRepository(HostelEntityRepository):
    entity = INVOICE

    async def find_by_invoice_id(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_entity({"data.invoice_id": invoice_id})

    async def update_by_invoice_id(
        self,
        invoice_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        return await self.update_entity({"data.invoice_id": invoice_id}, data)


class ComplaintRepository(HostelEntityRepository):
    entity = COMPLAINT

