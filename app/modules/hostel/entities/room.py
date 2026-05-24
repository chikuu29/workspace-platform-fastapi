from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.modules.hostel.entities.common import HostelEntity


ROOM = HostelEntity(entity_type="hostel_room", prefix="ROOM")


FLOOR_LABELS = {
    "0": "Ground Floor",
    "1": "1st Floor",
    "2": "2nd Floor",
    "3": "3rd Floor",
    "4": "4th Floor",
    "5": "5th Floor",
}


def normalize_room_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    data.setdefault("occupants", [])
    data.setdefault("capacity", 2)
    data.setdefault("status", "Empty")
    data.setdefault("rentAmount", 5000)
    return data


def capacity(room_data: Dict[str, Any]) -> int:
    return int(room_data.get("capacity") or 2)


def occupants(room_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(room_data.get("occupants") or [])


def occupancy_status(room_data: Dict[str, Any]) -> str:
    count = len(occupants(room_data))
    cap = capacity(room_data)
    if count == 0:
        return "Empty"
    if count >= cap:
        return "Fully Occupied"
    return "Partially Occupied"


def option_label(room_data: Dict[str, Any]) -> str:
    cap = capacity(room_data)
    count = len(occupants(room_data))
    room_number = room_data.get("roomNumber", "Unnamed Room")
    floor_value: Optional[Any] = room_data.get("floorNumber")
    floor_label = FLOOR_LABELS.get(str(floor_value)) if floor_value is not None else None

    if floor_label:
        return f"{room_number} ({floor_label} - {count}/{cap} occupied)"
    return f"{room_number} ({count}/{cap} occupied)"


def security_deposit(room_data: Dict[str, Any]) -> int:
    rent_amount = float(room_data.get("rentAmount") or 0.0)
    cap = capacity(room_data)
    if rent_amount <= 0 or cap <= 0:
        return 0
    return int((rent_amount / cap) * 2)
