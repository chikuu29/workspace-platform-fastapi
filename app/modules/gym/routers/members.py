"""
gym/routers/members.py — Gym member CRUD endpoints.
"""

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import ok, created, paginated, deleted
from app.core.utils import sanitize_payload
from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  MEMBER CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/members")
async def add_member(
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """
    Register a new gym member.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    result = await service.add_member(data)
    return created(
        message="Membership registration successful!",
        data=result,
    )


@router.get("/members")
async def get_members(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: GymService = Depends(get_gym_service),
):
    """
    List gym members with subscription summaries.
    """
    enriched, total = await service.list_members(skip=skip, limit=limit)
    return paginated(
        message="Members retrieved.",
        data=enriched,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/members/{identifier}")
async def get_member(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """Retrieve a single member with full subscription + plan details."""
    doc = await service.get_member_detail(identifier)
    return ok(message="Member retrieved.", data=doc)


@router.put("/members/{identifier}")
async def update_member(
    identifier: str,
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """
    Update a member's data fields.
    """
    raw = await request.json()
    update_data = sanitize_payload(raw)

    doc = await service.update_member(identifier, update_data)
    return ok(message="Member updated successfully.", data=doc)


@router.delete("/members/{identifier}")
async def delete_member(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """
    Soft-delete a member.
    """
    await service.delete_member(identifier)
    return deleted(message="Member deleted successfully.")
