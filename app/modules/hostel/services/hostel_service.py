from __future__ import annotations

from app.modules.hostel.services.analytics_service import HostelAnalyticsService
from app.modules.hostel.services.billing_service import HostelBillingService
from app.modules.hostel.services.building_service import HostelBuildingService
from app.modules.hostel.services.complaint_service import HostelComplaintService
from app.modules.hostel.services.guest_service import HostelGuestService
from app.modules.hostel.services.room_service import HostelRoomService


class HostelService(
    HostelAnalyticsService,
    HostelBuildingService,
    HostelRoomService,
    HostelGuestService,
    HostelBillingService,
    HostelComplaintService,
):
    """Facade service used by FastAPI dependencies.

    Domain logic lives in segregated service classes while the router keeps one
    dependency type.
    """

