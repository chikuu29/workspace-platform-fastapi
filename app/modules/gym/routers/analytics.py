"""
gym/routers/analytics.py — Dashboard KPI, subscription stats, and attendance analytics.
"""

from fastapi import APIRouter, Depends

from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD KPIs
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/kpis")
async def get_gym_kpis(
    service: GymService = Depends(get_gym_service),
):
    """
    Aggregate gym dashboard KPI data in a single backend call.
    """
    res = await service.get_kpis()
    return res


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION ANALYTICS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/subscriptions")
async def get_subscription_analytics(
    service: GymService = Depends(get_gym_service),
):
    """
    Aggregate subscription dashboard KPIs.
    """
    res = await service.get_subscription_analytics()
    return res


# ══════════════════════════════════════════════════════════════════════
#  ATTENDANCE ANALYTICS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/attendance")
async def get_attendance_analytics(
    service: GymService = Depends(get_gym_service),
):
    """
    Get attendance analytics: daily visits, hourly heatmap, and
    active vs slipping member counts.
    """
    res = await service.get_attendance_analytics()
    return res
