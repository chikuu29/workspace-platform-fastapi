"""
gym/routers/trainers.py — Gym trainer / staff CRUD endpoints.
"""

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import ok, created, paginated, deleted
from app.core.utils import sanitize_payload
from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  TRAINER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@router.post("/addTrainer")
async def add_trainer(
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """
    Register a new gym trainer / staff member.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    result = await service.add_trainer(data)
    return created(
        message="Trainer registration successful!",
        data=result,
    )


@router.get("/trainers")
async def get_trainers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: GymService = Depends(get_gym_service),
):
    """List all trainers in the organisation."""
    docs, total = await service.list_trainers(skip=skip, limit=limit)
    return paginated(
        message="Trainers retrieved.",
        data=docs,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/trainers/{identifier}")
async def get_trainer(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """Retrieve details of a specific trainer by id, trainer_id, or ObjectId."""
    doc = await service.get_trainer(identifier)
    return ok(message="Trainer retrieved.", data=doc)


@router.put("/trainers/{identifier}")
async def update_trainer(
    identifier: str,
    request: Request,
    service: GymService = Depends(get_gym_service),
):
    """Update trainer data."""
    raw = await request.json()
    update_data = sanitize_payload(raw)

    doc = await service.update_trainer(identifier, update_data)
    return ok(message="Trainer updated successfully.", data=doc)


@router.delete("/trainers/{identifier}")
async def delete_trainer(
    identifier: str,
    service: GymService = Depends(get_gym_service),
):
    """Soft-delete a trainer."""
    await service.delete_trainer(identifier)
    return deleted(message="Trainer deleted successfully.")
