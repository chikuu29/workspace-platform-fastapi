"""
Gym Module Router — CRUD operations for gym members, subscription plans,
and subscription activation.

All endpoints use OrgContext for secure multi-tenant data access.
- org_id / org_uuid → from JWT
- app_id → from x-app-code header
- request data → validated through sanitize_payload

Response contract (via app.common.responses):
    Success → { "success": True,  "message": "...", "data": {...} }
    Error   → { "success": False, "message": "...", "error_code": "..." }
"""

from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Depends, Query, Request
from bson import ObjectId

from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, paginated, deleted, not_found, bad_request, conflict
from app.db.database import get_database
from app.db.org_sequence import OrgSequenceService
from app.modules.gym.schemas import sanitize_payload

router = APIRouter(
    dependencies=[Depends(get_authenticated_identity)]
)

# ── Entity Constants ─────────────────────────────────────────────────
# Each entity_type corresponds to a logical collection within the shared
# `records` MongoDB collection, scoped by _org.org_id.

ENTITY_MEMBER = "member"
"""Canonical entity type for gym member documents."""

ENTITY_PLAN = "subscription_plan"
"""Canonical entity type for subscription plan templates."""

ENTITY_SUBSCRIPTION = "subscription"
"""Canonical entity type for active member ↔ plan subscription records."""

# ── Base Filters ─────────────────────────────────────────────────────

MEMBER_QUERY = {"_meta.entity_type": ENTITY_MEMBER}
"""Base filter that scopes all queries to member documents only."""

PLAN_QUERY = {"_meta.entity_type": ENTITY_PLAN}
"""Base filter that scopes all queries to subscription plan documents."""

SUBSCRIPTION_QUERY = {"_meta.entity_type": ENTITY_SUBSCRIPTION}
"""Base filter that scopes all queries to subscription documents."""


# ── Helpers ──────────────────────────────────────────────────────────

def _record_query(identifier: str) -> dict:
    """Build a flexible lookup query by record_id, member_id, or ObjectId."""
    query = {
        "$or": [
            {"_meta.record_id": identifier},
            {"data.member_id": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


def _plan_query(identifier: str) -> dict:
    """Build a flexible lookup query for plans by record_id, code, or ObjectId."""
    query = {
        "$or": [
            {"_meta.record_id": identifier},
            {"data.code": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


def _calculate_end_date(start_date: str, billing_cycle: str) -> str:
    """Calculate subscription end date based on billing cycle.

    Uses python-dateutil for accurate month/year arithmetic (handles
    edge cases like Feb 28 → Mar 28, etc.)
    """
    start = datetime.fromisoformat(start_date)
    cycle_map = {
        "monthly": relativedelta(months=1),
        "quarterly": relativedelta(months=3),
        "yearly": relativedelta(years=1),
    }
    delta = cycle_map.get(billing_cycle, relativedelta(months=1))
    end = start + delta
    return end.isoformat()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD STATS
# ══════════════════════════════════════════════════════════════════════

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Aggregate gym dashboard KPI data in a single backend call.
    Returns member counts by status and the 5 most recently enrolled members.
    """
    repo = OrgRepository(db, "records", ctx)

    # Aggregate counts
    total = await repo.count(MEMBER_QUERY)
    active = await repo.count({**MEMBER_QUERY, "data.status": "active"})
    attention = await repo.count({**MEMBER_QUERY, "data.status": "attention"})
    frozen = await repo.count({**MEMBER_QUERY, "data.status": "frozen"})

    # Monthly additions
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    added_this_month = await repo.count({
        **MEMBER_QUERY,
        "_meta.created.at": {"$gte": month_start},
    })

    # Recent members
    recent_docs = await repo.find(
        MEMBER_QUERY,
        sort=[("_meta.created.at", -1)],
        limit=5,
    )

    recent_members = [
        {
            "record_id": d["_meta"]["record_id"],
            "name": f"{d['data'].get('firstName', '')} {d['data'].get('lastName', '')}".strip() or "Unknown",
            "plan": d["data"].get("plan", "N/A"),
            "created_at": d["_meta"]["created"]["at"],
        }
        for d in recent_docs
    ]

    return ok(
        message="Dashboard stats retrieved.",
        data={
            "kpis": {
                "total_members": total,
                "active_members": active,
                "attention_members": attention,
                "frozen_members": frozen,
                "members_added_this_month": added_this_month,
                "revenue_mrr": 45200,           # Placeholder until billing module
                "checkins_today": 186,           # Placeholder until check-in module
                "trainer_utilization": 81,       # Placeholder until trainer module
            },
            "recent_members": recent_members,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  MEMBER CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/addMember")
async def add_member(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Register a new gym member.

    - Duplicate check on email / phone (org-scoped, strict match)
    - Data sanitized (XSS, injection prevention)
    - org_id, app_id, created_by injected from JWT + headers
    - record_id auto-generated by OrgRepository
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    # ── Duplicate prevention ─────────────────────────────────────────
    repo = OrgRepository(db, "records", ctx)

    duplicate_filters = []
    if data.get("email"):
        duplicate_filters.append({"data.email": data["email"]})
    if data.get("phone"):
        duplicate_filters.append({"data.phone": data["phone"]})

    if duplicate_filters:
        existing = await repo.find_one({
            **MEMBER_QUERY,
            "$or": duplicate_filters,
        })
        if existing:
            conflict(
                message="A member with this email or phone already exists.",
                error_code="DUPLICATE_MEMBER",
                details={
                    "existing_member_id": existing["data"].get("member_id"),
                    "existing_record_id": existing["_meta"]["record_id"],
                },
            )

    # ── Sequence + Insert ────────────────────────────────────────────
    seq = OrgSequenceService(db, ctx)
    member_id = await seq.simple("member", prefix="M")
    data["member_id"] = member_id

    document = await repo.insert_one(
        data=data,
        entity_type=ENTITY_MEMBER,
        prefix=ctx.app_code.upper(),
    )

    return created(
        message="Membership registration successful!",
        data={
            "record_id": document["_meta"]["record_id"],
            "member_id": member_id,
        },
    )


# ── READ (list) ─────────────────────────────────────────────────────

@router.get("/members")
async def get_members(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    List gym members for the current organization.

    Automatically scoped — Org A never sees Org B's members.
    """
    repo = OrgRepository(db, "records", ctx)

    documents = await repo.find(
        MEMBER_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(MEMBER_QUERY)

    return paginated(
        message="Members retrieved.",
        data=documents,
        total=total,
        skip=skip,
        limit=limit,
    )


# ── READ (single) ───────────────────────────────────────────────────

@router.get("/members/{identifier}")
async def get_member(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Retrieve a single member by record_id, member_id, or ObjectId."""
    repo = OrgRepository(db, "records", ctx)
    doc = await repo.find_one(_record_query(identifier))

    if not doc:
        not_found(message=f"Member '{identifier}' not found.")

    return ok(message="Member retrieved.", data=doc)


# ── UPDATE ───────────────────────────────────────────────────────────

@router.put("/members/{identifier}")
async def update_member(
    identifier: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Update a member's data fields.

    - Sanitized dynamically (any fields accepted)
    - `updated.by` and `updated.at` set automatically from JWT
    """
    raw = await request.json()
    update_data = sanitize_payload(raw)

    if not update_data:
        bad_request(message="No fields provided to update.")

    repo = OrgRepository(db, "records", ctx)
    doc = await repo.update_one(_record_query(identifier), update_data)

    if not doc:
        not_found(message=f"Member '{identifier}' not found.")

    return ok(message="Member updated successfully.", data=doc)


# ── DELETE (soft) ────────────────────────────────────────────────────

@router.delete("/members/{identifier}")
async def delete_member(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Soft-delete a member. Sets `_meta.is_deleted = true` with audit trail.

    The document is kept for compliance/recovery. It won't appear in
    normal queries but can be retrieved with include_deleted=True.
    """
    repo = OrgRepository(db, "records", ctx)
    result = await repo.soft_delete(_record_query(identifier))

    if not result:
        not_found(message=f"Member '{identifier}' not found.")

    return deleted(message="Member deleted successfully.")


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION PLAN CRUD
# ══════════════════════════════════════════════════════════════════════

@router.post("/plans")
async def create_plan(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
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
    existing = await repo.find_one({
        **PLAN_QUERY,
        "data.code": data["code"],
    })
    if existing:
        conflict(
            message=f"A plan with code '{data['code']}' already exists.",
            error_code="DUPLICATE_PLAN_CODE",
            details={
                "existing_record_id": existing["_meta"]["record_id"],
            },
        )

    # ── Defaults ─────────────────────────────────────────────────────
    data.setdefault("currency", "USD")
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
    db=Depends(get_database),
):
    """
    List all subscription plans for the current organization.

    Pass `active_only=true` to filter out inactive plans (useful for
    member-facing plan selection like CreateSubscription).
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
    db=Depends(get_database),
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
    db=Depends(get_database),
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
    db=Depends(get_database),
):
    """Soft-delete a subscription plan."""
    repo = OrgRepository(db, "records", ctx)
    result = await repo.soft_delete({**PLAN_QUERY, **_plan_query(identifier)})

    if not result:
        not_found(message=f"Subscription plan '{identifier}' not found.")

    return deleted(message="Plan deleted successfully.")


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION ACTIVATION
# ══════════════════════════════════════════════════════════════════════

@router.post("/subscriptions/activate")
async def activate_subscription(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Activate a subscription — links a member to a subscription plan.

    Expected payload:
        {
            "member_id": "M-1",
            "plan_code": "GYM_PRO",
            "start_date": "2026-05-04",
            "is_paid": true,
            "payment_amount": 89.00,
            "notes": "Signup promo applied"
        }

    This endpoint:
    1. Validates the member exists and is not already subscribed
    2. Validates the plan exists and is active
    3. Creates a subscription record (entity_type: "subscription")
    4. Updates the member's data.plan and data.status fields
    5. Returns the subscription record + updated member
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    member_id = data.get("member_id")
    plan_code = data.get("plan_code")
    start_date = data.get("start_date")

    if not member_id:
        bad_request(message="member_id is required.")
    if not plan_code:
        bad_request(message="plan_code is required.")

    repo = OrgRepository(db, "records", ctx)

    # ── 1. Verify member exists ──────────────────────────────────────
    member_doc = await repo.find_one({
        **MEMBER_QUERY,
        "$or": [
            {"data.member_id": member_id},
            {"_meta.record_id": member_id},
        ],
    })
    if not member_doc:
        not_found(message=f"Member '{member_id}' not found.")

    # ── 2. Verify plan exists and is active ──────────────────────────
    plan_doc = await repo.find_one({
        **PLAN_QUERY,
        "data.code": plan_code,
        "data.is_active": True,
    })
    if not plan_doc:
        not_found(message=f"Active plan with code '{plan_code}' not found.")

    # ── 3. Check for existing active subscription ────────────────────
    existing_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active",
    })
    if existing_sub:
        conflict(
            message=f"Member '{member_id}' already has an active subscription.",
            error_code="ACTIVE_SUBSCRIPTION_EXISTS",
            details={
                "existing_subscription_id": existing_sub["_meta"]["record_id"],
                "existing_plan": existing_sub["data"].get("plan_name"),
            },
        )

    # ── 4. Calculate subscription dates ──────────────────────────────
    plan_data = plan_doc["data"]
    billing_cycle = plan_data.get("billing_cycle", "monthly")

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    end_date = _calculate_end_date(start_date, billing_cycle)

    # ── 5. Build subscription record ─────────────────────────────────
    subscription_data = {
        "member_id": member_id,
        "member_name": f"{member_doc['data'].get('firstName', '')} {member_doc['data'].get('lastName', '')}".strip(),
        "plan_code": plan_code,
        "plan_name": plan_data.get("name", ""),
        "plan_record_id": plan_doc["_meta"]["record_id"],
        "price": plan_data.get("price", 0),
        "currency": plan_data.get("currency", "USD"),
        "billing_cycle": billing_cycle,
        "start_date": start_date,
        "end_date": end_date,
        "status": "active",
        "is_paid": data.get("is_paid", False),
        "payment_amount": data.get("payment_amount", plan_data.get("price", 0)),
        "notes": data.get("notes", ""),
    }

    seq = OrgSequenceService(db, ctx)
    subscription_id = await seq.simple("subscription", prefix="SUB")
    subscription_data["subscription_id"] = subscription_id

    subscription_doc = await repo.insert_one(
        data=subscription_data,
        entity_type=ENTITY_SUBSCRIPTION,
        prefix=ctx.app_code.upper(),
    )

    # ── 6. Update member with plan + status ──────────────────────────
    member_update = {
        "plan": plan_data.get("name", plan_code),
        "plan_code": plan_code,
        "subscription_id": subscription_id,
        "status": "active",
    }
    await repo.update_one(
        {**MEMBER_QUERY, "data.member_id": member_id},
        member_update,
    )

    return created(
        message="Subscription activated successfully!",
        data={
            "subscription": subscription_doc,
            "subscription_id": subscription_id,
            "member_id": member_id,
            "plan_name": plan_data.get("name"),
            "start_date": start_date,
            "end_date": end_date,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION STATS
# ══════════════════════════════════════════════════════════════════════

@router.get("/subscription/stats")
async def get_subscription_stats(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Aggregate subscription dashboard KPIs.

    Returns plan counts, subscriber counts, and revenue breakdown
    per plan for the current organization.
    """
    repo = OrgRepository(db, "records", ctx)

    # Plan-level stats
    total_plans = await repo.count(PLAN_QUERY)
    active_plans = await repo.count({**PLAN_QUERY, "data.is_active": True})

    # Subscription-level stats
    total_subscribers = await repo.count({
        **SUBSCRIPTION_QUERY,
        "data.status": "active",
    })

    # Per-plan breakdown — fetch all active plans, then count subscribers
    plan_docs = await repo.find(
        {**PLAN_QUERY, "data.is_active": True},
        sort=[("data.price", -1)],
        limit=50,
    )

    plans_with_members = []
    total_mrr = 0

    for plan in plan_docs:
        plan_code = plan["data"].get("code", "")
        member_count = await repo.count({
            **SUBSCRIPTION_QUERY,
            "data.plan_code": plan_code,
            "data.status": "active",
        })

        price = plan["data"].get("price", 0)
        billing_cycle = plan["data"].get("billing_cycle", "monthly")

        # Normalize to monthly revenue for MRR calculation
        if billing_cycle == "quarterly":
            monthly_price = price / 3
        elif billing_cycle == "yearly":
            monthly_price = price / 12
        else:
            monthly_price = price

        plan_revenue = monthly_price * member_count
        total_mrr += plan_revenue

        plans_with_members.append({
            "plan_code": plan_code,
            "plan_name": plan["data"].get("name", ""),
            "price": price,
            "billing_cycle": billing_cycle,
            "member_count": member_count,
            "revenue": round(plan_revenue, 2),
            "accent_color": plan["data"].get("accent_color", "blue"),
        })

    return ok(
        message="Subscription stats retrieved.",
        data={
            "total_plans": total_plans,
            "active_plans": active_plans,
            "total_subscribers": total_subscribers,
            "total_mrr": round(total_mrr, 2),
            "plans_with_members": plans_with_members,
        },
    )
