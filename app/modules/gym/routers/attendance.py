"""
gym/routers/attendance.py — Member check-in recording.
"""

from fastapi import APIRouter, Depends

from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService
from app.common.responses import ok
router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  ATTENDANCE & CHECK-IN
# ══════════════════════════════════════════════════════════════════════

@router.post("/checkin")
async def member_checkin(
    data: dict,
    service: GymService = Depends(get_gym_service),
):
    """
    Record a member check-in event.
    """
    doc = await service.member_checkin(data)
    return ok(data=doc,message="Member check-in recorded successfully.")
