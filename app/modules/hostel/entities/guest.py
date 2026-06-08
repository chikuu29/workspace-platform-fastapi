from __future__ import annotations

from typing import Any, Dict

from app.modules.hostel.entities.common import HostelEntity


GUEST = HostelEntity(entity_type="hostel_guest", prefix="GST")
TENANT = GUEST


def full_name(data: Dict[str, Any]) -> str:
    return f"{data.get('firstName', '')} {data.get('lastName', '')}".strip()


def occupant_reference(guest_id: str, guest_doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "guest_id": guest_id,
        
        "id": guest_doc["_meta"]["id"],
    }
