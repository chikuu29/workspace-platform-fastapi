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

from datetime import datetime, timezone, timedelta
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

ENTITY_TRAINER = "trainer"
"""Canonical entity type for gym trainer/staff records."""

ENTITY_ATTENDANCE = "attendance"
"""Canonical entity type for member check-in records."""

# ── Base Filters ─────────────────────────────────────────────────────

MEMBER_QUERY = {"_meta.entity_type": ENTITY_MEMBER}
PLAN_QUERY = {"_meta.entity_type": ENTITY_PLAN}
SUBSCRIPTION_QUERY = {"_meta.entity_type": ENTITY_SUBSCRIPTION}
ATTENDANCE_QUERY = {"_meta.entity_type": ENTITY_ATTENDANCE}
TRAINER_QUERY = {"_meta.entity_type": ENTITY_TRAINER}


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

@router.get("/analytics/kpis")
async def get_gym_kpis(
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

    # ── Real-time Analytics ──────────────────────────────────────────
    
    # 1. Revenue MRR: Sum of prices from active subscriptions
    revenue_pipeline = [
        {"$match": {**ctx.active_filter, **SUBSCRIPTION_QUERY, "data.status": "active"}},
        {"$group": {"_id": None, "total": {"$sum": "$data.price"}}}
    ]
    revenue_cursor = repo.collection.aggregate(revenue_pipeline)
    revenue_result = await revenue_cursor.to_list(length=1)
    revenue_mrr = revenue_result[0]["total"] if revenue_result else 0

    # 2. Check-ins Today: Records from attendance collection for the current UTC day
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    checkins_today = await repo.count({
        **ATTENDANCE_QUERY,
        "_meta.created.at": {"$gte": today_start},
    })

    # 3. Trainer Utilization: Percentage of trainers currently active
    total_trainers = await repo.count(TRAINER_QUERY)
    active_trainers = await repo.count({**TRAINER_QUERY, "data.status": "active"})
    trainer_utilization = round((active_trainers / total_trainers * 100)) if total_trainers > 0 else 0

    return ok(
        message="Dashboard statistics retrieved.",
        data={
            "kpis": {
                "total_members": total,
                "active_members": active,
                "attention_members": attention,
                "frozen_members": frozen,
                "members_added_this_month": added_this_month,
                "total_trainers": total_trainers,
                "revenue_mrr": revenue_mrr,
                "checkins_today": checkins_today,
                "trainer_utilization": trainer_utilization,
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


async def _enrich_member(member: dict, repo: OrgRepository) -> dict:
    """Attach subscription summary and compute dynamic status.

    Status is derived from subscription state — never stored statically:
    - **active**: Has an active, paid subscription with time remaining
    - **attention**: Subscription exists but is unpaid or expires within 7 days
    - **frozen**: No active subscription, or subscription has expired
    """
    member_id = member["data"].get("member_id")
    if not member_id:
        member["subscription"] = None
        member["has_plan"] = False
        member["data"]["status"] = "frozen"
        return member

    sub_doc = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active",
    })

    if sub_doc:
        sub = sub_doc["data"]
        member["subscription"] = {
            "subscription_id": sub.get("subscription_id"),
            "plan_name": sub.get("plan_name"),
            "plan_code": sub.get("plan_code"),
            "price": sub.get("price", 0),
            "currency": sub.get("currency", "INR"),
            "billing_cycle": sub.get("billing_cycle"),
            "start_date": sub.get("start_date"),
            "end_date": sub.get("end_date"),
            "status": sub.get("status"),
            "is_paid": sub.get("is_paid", False),
        }
        member["has_plan"] = True

        # ── Dynamic status calculation ───────────────────────────
        now = datetime.now(timezone.utc)
        end_date_str = sub.get("end_date")
        is_paid = sub.get("is_paid", False)

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str)
                # Make timezone-aware if naive
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)

                days_remaining = (end_date - now).days

                if days_remaining < 0:
                    # Subscription expired
                    member["data"]["status"] = "frozen"
                elif not is_paid:
                    # Active but unpaid — needs follow-up
                    member["data"]["status"] = "attention"
                elif days_remaining <= 7:
                    # Expiring within 7 days — renewal reminder
                    member["data"]["status"] = "attention"
                else:
                    member["data"]["status"] = "active"
            except (ValueError, TypeError):
                # Bad date format — flag for review
                member["data"]["status"] = "attention"
        else:
            # No end date recorded
            member["data"]["status"] = "attention" if not is_paid else "active"
    else:
        member["subscription"] = None
        member["has_plan"] = False
        member["data"]["status"] = "frozen"

    return member


@router.get("/members")
async def get_members(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    List gym members with subscription summaries.

    Each member document is enriched with:
    - `subscription`: active subscription details (or null)
    - `has_plan`: boolean flag for frontend card highlighting
    """
    repo = OrgRepository(db, "records", ctx)

    documents = await repo.find(
        MEMBER_QUERY,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(MEMBER_QUERY)

    # Enrich each member with subscription data
    enriched = [await _enrich_member(doc, repo) for doc in documents]

    return paginated(
        message="Members retrieved.",
        data=enriched,
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
    """Retrieve a single member with full subscription + plan details.

    Returns the member document enriched with:
    - `subscription`: active subscription record (or null)
    - `plan_details`: full plan document (or null)
    - `has_plan`: boolean flag
    - `subscription_history`: list of all past subscriptions
    """
    repo = OrgRepository(db, "records", ctx)
    doc = await repo.find_one(_record_query(identifier))

    if not doc:
        not_found(message=f"Member '{identifier}' not found.")

    # Enrich with subscription summary
    doc = await _enrich_member(doc, repo)

    # For single-member view, also attach full plan details + history
    member_id = doc["data"].get("member_id")
    if member_id and doc.get("subscription"):
        plan_code = doc["subscription"].get("plan_code")
        if plan_code:
            plan_doc = await repo.find_one({
                **PLAN_QUERY,
                "data.code": plan_code,
            })
            doc["plan_details"] = plan_doc["data"] if plan_doc else None
        else:
            doc["plan_details"] = None
    else:
        doc["plan_details"] = None

    # Subscription history (all subscriptions, not just active)
    if member_id:
        all_subs = await repo.find(
            {**SUBSCRIPTION_QUERY, "data.member_id": member_id},
            sort=[("_meta.created.at", -1)],
            limit=20,
        )
        doc["subscription_history"] = [
            {
                "subscription_id": s["data"].get("subscription_id"),
                "plan_name": s["data"].get("plan_name"),
                "status": s["data"].get("status"),
                "start_date": s["data"].get("start_date"),
                "end_date": s["data"].get("end_date"),
                "price": s["data"].get("price", 0),
                "is_paid": s["data"].get("is_paid", False),
            }
            for s in all_subs
        ]
    else:
        doc["subscription_history"] = []

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

    # ── 5. Generate Billing Invoice ──────────────────────────────────
    member_name = f"{member_doc['data'].get('firstName', '')} {member_doc['data'].get('lastName', '')}".strip()
    seller_gstin = "29AABCU9603R1ZM"  # Default fallback
    tax_profile = await db["billing_tax_profiles"].find_one({"_org.org_id": ctx.org_id})
    if tax_profile:
        seller_gstin = tax_profile.get("data", {}).get("gstin", seller_gstin)


    

    from app.modules.billing_management.services.invoice_service import InvoiceService
    from app.modules.billing_management.schemas.invoice_schemas import CreateInvoiceInput
    from app.modules.billing_management.schemas.line_items import ServiceLineItem
    from app.modules.billing_management.schemas.common import CustomerRefSchema

    billing_input = CreateInvoiceInput(
        customer_ref=CustomerRefSchema(
            ref_type="member",
            ref_id=member_id,
            name=member_name,
            email=member_doc["data"].get("email", ""),
            phone=member_doc["data"].get("phone", ""),
        ),
        line_items=[
            ServiceLineItem(
                item_type="service",
                description=f"Gym Subscription: {plan_data.get('name')}",
                quantity=1,
                unit_price=plan_data.get("price", 0),
                hsn_sac_code="997212",  # Gym/Fitness SAC code
                tax_category="higher",  # 18% standard GST
                source_item_code=plan_code,
            )
        ],
        seller_gstin=seller_gstin,
        place_of_supply=seller_gstin[:2],
        due_date=end_date,
        notes=data.get("notes", ""),
    )

    invoice_svc = InvoiceService(db, ctx)
    invoice_doc = await invoice_svc.create_invoice(billing_input)

    # ── 6. Handle Payment Recording ──────────────────────────────────
    is_paid = data.get("is_paid", False)
    payment_method = data.get("payment_method", "cash")
    transaction_ref = data.get("transaction_ref", "")

    if is_paid:
        from app.modules.billing_management.services.payment_service import PaymentService
        from app.modules.billing_management.schemas.payment_schemas import RecordPaymentInput

        payment_svc = PaymentService(db, ctx)
        payment_input = RecordPaymentInput(
            invoice_ref=invoice_doc.invoice_number,
            amount=invoice_doc.total,
            method=payment_method,
            transaction_ref=transaction_ref,
            notes=f"Upfront subscription payment via {payment_method.upper()}",
        )
        await payment_svc.record_payment(payment_input)

        # Reload updated invoice doc
        invoice_doc_tuple = await invoice_svc.get_invoice(invoice_doc.invoice_number)
        invoice_doc = invoice_doc_tuple[0]
    else:
        if payment_method == "payment_link":
            import logging
            logger = logging.getLogger("app")
            logger.info(f"Payment Link Dispatch: Secure link created for Invoice {invoice_doc.invoice_number} and sent to customer email {member_doc['data'].get('email', 'N/A')}")
            invoice_doc = await invoice_svc.send_invoice(invoice_doc.invoice_number)

    # ── 7. Build subscription record ─────────────────────────────────
    subscription_data = {
        "member_id": member_id,
        "member_name": member_name,
        "plan_code": plan_code,
        "plan_name": plan_data.get("name", ""),
        "plan_record_id": plan_doc["_meta"]["record_id"],
        "price": plan_data.get("price", 0),
        "currency": plan_data.get("currency", "INR"),
        "billing_cycle": billing_cycle,
        "start_date": start_date,
        "end_date": end_date,
        "status": "active",
        "is_paid": is_paid,
        "payment_method": payment_method,
        "payment_amount": invoice_doc.total,
        "invoice_number": invoice_doc.invoice_number,
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

    # ── 8. Update member with plan + status ──────────────────────────
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
            "invoice": {
                "invoice_number": invoice_doc.invoice_number,
                "total": invoice_doc.total,
                "status": invoice_doc.status,
                "balance_due": invoice_doc.balance_due,
            },
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION STATS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/subscriptions")
async def get_subscription_analytics(
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


# ── Trainer Helpers ───────────────────────────────────────────────────

def _trainer_query(identifier: str) -> dict:
    """Build a flexible lookup query for trainers by record_id, trainer_id, or ObjectId."""
    query = {
        "$or": [
            {"_meta.record_id": identifier},
            {"data.trainer_id": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


# ══════════════════════════════════════════════════════════════════════
#  TRAINER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════

@router.post("/addTrainer")
async def add_trainer(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Register a new gym trainer/staff member.

    - Duplicate check on email/phone
    - Auto-generates trainer_id (prefix TR)
    - Fully audited record creation
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    repo = OrgRepository(db, "records", ctx)

    # ── Duplicate check ──────────────────────────────────────────────
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
    db=Depends(get_database),
):
    """List all trainers in the organization."""
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
    db=Depends(get_database),
):
    """Retrieve details of a specific trainer."""
    repo = OrgRepository(db, "records", ctx)
    doc = await repo.find_one(_trainer_query(identifier))
    if not doc:
        not_found(message=f"Trainer '{identifier}' not found.")
    return ok(message="Trainer retrieved.", data=doc)


@router.put("/trainers/{identifier}")
async def update_trainer(
    identifier: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Update trainer data."""
    raw = await request.json()
    update_data = sanitize_payload(raw)

    if not update_data:
        bad_request(message="No fields provided to update.")

    repo = OrgRepository(db, "records", ctx)
    doc = await repo.update_one(_trainer_query(identifier), update_data)
    if not doc:
        not_found(message=f"Trainer '{identifier}' not found.")

    return ok(message="Trainer updated successfully.", data=doc)


@router.delete("/trainers/{identifier}")
async def delete_trainer(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """Soft-delete a trainer."""
    repo = OrgRepository(db, "records", ctx)
    result = await repo.soft_delete(_trainer_query(identifier))
    if not result:
        not_found(message=f"Trainer '{identifier}' not found.")
    return deleted(message="Trainer deleted successfully.")


# ══════════════════════════════════════════════════════════════════════
#  ATTENDANCE & CHECK-IN
# ══════════════════════════════════════════════════════════════════════

@router.post("/checkin")
async def member_checkin(
    data: dict,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Record a member check-in.
    Payload: { "member_id": "M-11" }
    """
    repo = OrgRepository(db, "records", ctx)
    member_id = data.get("member_id")

    if not member_id:
        bad_request(message="member_id is required.")

    # 1. Verify member exists
    member_doc = await repo.find_one({**MEMBER_QUERY, "data.member_id": member_id})
    if not member_doc:
        not_found(message=f"Member {member_id} not found.")

    # 2. Verify active subscription (optional but recommended)
    sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active"
    })

    # 3. Create attendance record
    now = datetime.now(timezone.utc)
    checkin_data = {
        "member_id": member_id,
        "member_name": f"{member_doc['data'].get('firstName', '')} {member_doc['data'].get('lastName', '')}".strip(),
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.hour,
        "subscription_id": sub["data"]["subscription_id"] if sub else None,
        "has_active_plan": bool(sub)
    }

    doc = await repo.insert_one(
        data=checkin_data,
        entity_type=ENTITY_ATTENDANCE,
        prefix=ctx.app_code.upper()
    )

    return created(message="Check-in successful!", data=doc)


@router.get("/analytics/attendance")
async def get_attendance_analytics(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Get attendance analytics: daily visits, hourly heatmap, and active vs slipping members.
    """
    repo = OrgRepository(db, "records", ctx)
    now = datetime.now(timezone.utc)

    # 1. Visits last 7 days
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    daily_visits = []
    for d in reversed(dates):
        count = await repo.count({**ATTENDANCE_QUERY, "data.date": d})
        daily_visits.append({"date": d, "count": count})

    # 2. Hourly Heatmap (last 30 days)
    # Simple aggregation loop since we don't have complex mongo pipeline tool ready
    hourly_dist = {h: 0 for h in range(24)}
    checkins = await repo.find(ATTENDANCE_QUERY, limit=1000)
    for c in checkins:
        h = c["data"].get("hour")
        if h is not None:
            hourly_dist[h] += 1

    heatmap = [{"hour": h, "count": count} for h, count in hourly_dist.items()]

    # 3. Active Members (checked in last 7 days)
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    active_member_ids = await db["records"].distinct(
        "data.member_id",
        {
            **ATTENDANCE_QUERY,
            "_org.org_id": ctx.org_id,
            "data.timestamp": {"$gte": seven_days_ago}
        }
    )

    total_members = await repo.count(MEMBER_QUERY)

    return ok(data={
        "daily_visits": daily_visits,
        "hourly_heatmap": heatmap,
        "active_last_7_days": len(active_member_ids),
        "total_members": total_members,
        "slipping_members": max(0, total_members - len(active_member_ids))
    })
