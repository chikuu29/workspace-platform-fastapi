"""
gym/routers/plans.py — Subscription plan template CRUD.
"""

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import ok, created, paginated, deleted
from app.core.utils import sanitize_payload
from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION PLAN CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/plans")
async def create_plan(
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """
    Create a new subscription plan template.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    document = await service.create_plan(data)
    return created(
        message="Subscription plan created successfully.",
        data=document,
    )


@router.get("/plans")
async def get_plans(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    active_only: bool = Query(False),
    service: GymService = Depends(get_gym_service),
):
    """
    List all subscription plans for the current organization.
    """
    documents, total = await service.list_plans(active_only=active_only, skip=skip, limit=limit)
    return paginated(
        message="Subscription plans retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/plans/{identifier}")
async def get_plan(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """Retrieve a single subscription plan by id, code, or ObjectId."""
    doc = await service.get_plan(identifier)
    return ok(message="Plan retrieved.", data=doc)


@router.put("/plans/{identifier}")
async def update_plan(
    identifier: str,
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """Update a subscription plan's data fields."""
    raw = await request.json()
    update_data = sanitize_payload(raw)

    doc = await service.update_plan(identifier, update_data)
    return ok(message="Plan updated successfully.", data=doc)


@router.delete("/plans/{identifier}")
async def delete_plan(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """Soft-delete a subscription plan."""
    await service.delete_plan(identifier)
    return deleted(message="Plan deleted successfully.")
