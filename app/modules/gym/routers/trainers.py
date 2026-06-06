"""
gym/routers/trainers.py — Gym trainer / staff CRUD endpoints.

Endpoints:
    POST   /addTrainer              — Register a new trainer
    GET    /trainers                — List trainers (paginated)
    GET    /trainers/{identifier}   — Get trainer by record_id, trainer_id, or ObjectId
    PUT    /trainers/{identifier}   — Update trainer data fields
    DELETE /trainers/{identifier}   — Soft-delete trainer
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, paginated, deleted, not_found, bad_request, conflict
from app.core.database import get_db
from app.db.org_sequence import OrgSequenceService
from app.modules.gym.schemas import sanitize_payload
from app.modules.gym.routers.constants import (
    ENTITY_TRAINER,
    TRAINER_QUERY,
    _trainer_query,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  TRAINER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@router.post("/addTrainer")
async def add_trainer(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Register a new gym trainer / staff member.

    - Duplicate check on email / phone
    - Auto-generates trainer_id (prefix TR)
    - Fully audited record creation
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    repo = OrgRepository(db, "records", ctx)

    # ── Duplicate prevention ─────────────────────────────────────────
    dup_filters = []
    if data.get("email"):
        dup_filters.append({"data.email": data["email"]})
    if data.get("phone"):
        dup_filters.append({"data.phone": data["phone"]})

    if dup_filters:
        existing = await repo.find_one({**TRAINER_QUERY, "$or": dup_filters})
        if existing:
            conflict(
                message="A trainer with this email or phone already exists.",
                error_code="DUPLICATE_TRAINER",
            )

    # ── Sequence + Insert ────────────────────────────────────────────
    seq = OrgSequenceService(db, ctx)
    trainer_id = await seq.simple("trainer", prefix="TR")
    data["trainer_id"] = trainer_id

    document = await repo.insert_one(
        data=data,
        entity_type=ENTITY_TRAINER,
        prefix=ctx.app_code.upper(),
    )

    return created(
        message="Trainer registration successful!",
        data={
            "record_id": document["_meta"]["record_id"],
            "trainer_id": trainer_id,
        },
    )


@router.get("/trainers")
async def get_trainers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """List all trainers in the organisation."""
    repo = OrgRepository(db, "records", ctx)
    docs = await repo.find(
        TRAINER_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(TRAINER_QUERY)

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
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Retrieve details of a specific trainer by record_id, trainer_id, or ObjectId."""
    repo = OrgRepository(db, "records", ctx)
    doc = await repo.find_one({**TRAINER_QUERY, **_trainer_query(identifier)})

    if not doc:
        not_found(message=f"Trainer '{identifier}' not found.")

    return ok(message="Trainer retrieved.", data=doc)


@router.put("/trainers/{identifier}")
async def update_trainer(
    identifier: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Update trainer data."""
    raw = await request.json()
    update_data = sanitize_payload(raw)

    if not update_data:
        bad_request(message="No fields provided to update.")

    repo = OrgRepository(db, "records", ctx)
    doc = await repo.update_one({**TRAINER_QUERY, **_trainer_query(identifier)}, update_data)

    if not doc:
        not_found(message=f"Trainer '{identifier}' not found.")

    return ok(message="Trainer updated successfully.", data=doc)


@router.delete("/trainers/{identifier}")
async def delete_trainer(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Soft-delete a trainer."""
    repo = OrgRepository(db, "records", ctx)
    result = await repo.soft_delete({**TRAINER_QUERY, **_trainer_query(identifier)})

    if not result:
        not_found(message=f"Trainer '{identifier}' not found.")

    return deleted(message="Trainer deleted successfully.")
