"""
gym/routers/analytics.py — Dashboard KPIs and widget-driven chart analytics.

Two endpoints:
    GET  /analytics              — Dashboard KPIs + recent enrollments
    GET  /analytics/{widget}     — Dynamic widget data (chart_type, series)

The widget endpoint dispatches to handlers registered in GymService.WIDGET_REGISTRY.
Adding a new chart widget requires only 1 handler method + 1 registry entry.

Frontend can override chart_type via ?chart_type= query param, and the backend
will reshape the series data to match the target shape group.
"""

from fastapi import APIRouter, Depends, Request

from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService
from app.common.responses import ok, not_found

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD KPIs + RECENT ENROLLMENTS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics")
async def get_dashboard_analytics(
    service: GymService = Depends(get_gym_service),
):
    """Basic dashboard data — scalar KPIs and recent member enrollments.

    Used by the StatCard row and RecentEnrollmentsList components.
    """
    res = await service.get_kpis()
    return ok(data=res, message="Dashboard analytics")


# ══════════════════════════════════════════════════════════════════════
#  MEMBER ATTENDANCE REPORTS
# ══════════════════════════════════════════════════════════════════════

from typing import Optional

@router.get("/analytics/attendance/member/{member_id}")
async def get_member_attendance_report(
    member_id: str,
    year: Optional[int] = None,
    month: Optional[int] = None,
    service: GymService = Depends(get_gym_service),
):
    """Retrieve month-wise attendance report and full history for a member."""
    res = await service.get_member_attendance_report(member_id, year, month)
    return ok(data=res, message="Member attendance report")


# ══════════════════════════════════════════════════════════════════════
#  DYNAMIC WIDGET DATA
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/{widget_name}")
async def get_widget_data(
    widget_name: str,
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """Dynamic widget endpoint — dispatches to a registered handler.

    The response envelope includes chart_type, title, subtitle, optional
    filters, and series data so the frontend ChartCard can auto-configure.

    Query params are forwarded to the handler (e.g. ?range=30d, ?days=7).
    Frontend can override chart_type via ?chart_type=bar to reshape data.
    """
    params = dict(request.query_params)
    data = await service.get_widget_data(widget_name, params)
    if data is None:
        not_found(message=f"Widget '{widget_name}' is not registered.")
    return ok(data=data, message=f"Widget: {widget_name}")
