from __future__ import annotations

from app.modules.hostel.entities.common import HostelEntity


INVOICE = HostelEntity(entity_type="hostel_invoice", prefix="INV")
COMPLAINT = HostelEntity(entity_type="hostel_complaint", prefix="TKT")
