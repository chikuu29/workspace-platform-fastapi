from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.context import OrgContext
from app.modules.hostel.repositories.billing_repository import (
    ComplaintRepository,
    InvoiceRepository,
)
from app.modules.hostel.repositories.building_repository import BuildingRepository
from app.modules.hostel.repositories.guest_repository import GuestRepository
from app.modules.hostel.repositories.room_repository import RoomRepository


class HostelRepositories:
    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self.buildings = BuildingRepository(db, ctx)
        self.rooms = RoomRepository(db, ctx)
        self.guests = GuestRepository(db, ctx)
        self.invoices = InvoiceRepository(db, ctx)
        self.complaints = ComplaintRepository(db, ctx)

