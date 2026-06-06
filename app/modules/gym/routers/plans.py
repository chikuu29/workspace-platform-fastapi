"""
gym/routers/plans.py — Subscription plan template CRUD.

Endpoints:
    POST   /plans              — Create a new plan
    GET    /plans              — List plans (paginated, optional active_only filter)
    GET    /plans/{identifier} — Retrieve a single plan
    PUT    /plans/{identifier} — Update plan fields
    DELETE /plans/{identifier} — Soft-delete plan
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, paginated, deleted, not_found, bad_request, conflict
from app.core.database import get_db
from app.modules.gym.schemas import sanitize_payload
from app.modules.gym.routers.constants import (
    ENTITY_PLAN,
    PLAN_QUERY,
    _plan_query,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION PLAN CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/plans")
async def create_plan(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Create a new subscription plan template.

    - Duplicate check on plan code (org-scoped)
    - data.code must be unique within the organization
    - record_id auto-generated: MYGYM-202605-0001
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    if not data.get("name"):
        bad_request(message="Plan name is required.")
    if not data.get("code"):
        bad_request(message="Plan code is required.")

    repo = OrgRepository(db, "records", ctx)

    # ── Duplicate prevention on plan code ────────────────────────────
    existing = await repo.find_one({**PLAN_QUERY, "data.code": data["code"]})
    if existing:
        conflict(
            message=f"A plan with code '{data['code']}' already exists.",
            error_code="DUPLICATE_PLAN_CODE",
            details={"existing_record_id": existing["_meta"]["record_id"]},
        )

    # ── Defaults — applied only when the caller omits the field ──────
    data.setdefault("currency", "INR")
    data.setdefault("billing_cycle", "monthly")
    data.setdefault("is_active", True)
    data.setdefault("features", [])
    data.setdefault("accent_color", "blue")

    document = await repo.insert_one(
        data=data,
        entity_type=ENTITY_PLAN,
        prefix=ctx.app_code.upper(),
    )

    return created(
        message="Subscription plan created successfully.",
        data=document,
    )


@router.get("/plans")
async def get_plans(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    active_only: bool = Query(False),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    List all subscription plans for the current organization.

    Pass `active_only=true` to filter out inactive plans (useful for
    member-facing plan selection in CreateSubscription).
    """
    repo = OrgRepository(db, "records", ctx)

    query = {**PLAN_QUERY}
    if active_only:
        query["data.is_active"] = True

    documents = await repo.find(
        query,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(query)

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
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Retrieve a single subscription plan by record_id, code, or ObjectId."""
    repo = OrgRepository(db, "records", ctx)
    doc = await repo.find_one({**PLAN_QUERY, **_plan_query(identifier)})

    if not doc:
        not_found(message=f"Subscription plan '{identifier}' not found.")

    return ok(message="Plan retrieved.", data=doc)


@router.put("/plans/{identifier}")
async def update_plan(
    identifier: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Update a subscription plan's data fields."""
    raw = await request.json()
    update_data = sanitize_payload(raw)

    if not update_data:
        bad_request(message="No fields provided to update.")

    repo = OrgRepository(db, "records", ctx)
    doc = await repo.update_one(
        {**PLAN_QUERY, **_plan_query(identifier)},
        update_data,
    )

    if not doc:
        not_found(message=f"Subscription plan '{identifier}' not found.")

    return ok(message="Plan updated successfully.", data=doc)


@router.delete("/plans/{identifier}")
async def delete_plan(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """Soft-delete a subscription plan."""
    repo = OrgRepository(db, "records", ctx)
    result = await repo.soft_delete({**PLAN_QUERY, **_plan_query(identifier)})

    if not result:
        not_found(message=f"Subscription plan '{identifier}' not found.")

    return deleted(message="Plan deleted successfully.")
