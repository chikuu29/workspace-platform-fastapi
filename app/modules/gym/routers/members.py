"""
gym/routers/members.py — Gym member CRUD endpoints.
"""

from fastapi import APIRouter, Depends, Query, Request
from typing import Any, Dict, List, Optional


from app.common.responses import ok, created, paginated, deleted
from app.core.utils import sanitize_payload
from app.modules.gym.dependencies import get_gym_service
from app.modules.gym.service import GymService

# Scoped org context, database, and repository imports
from app.core.context import OrgContext, get_org_context
from app.core.database import get_db
from app.common.org_repository import OrgRepository

# Constants and query utilities for gym entities
from app.modules.gym.routers.constants import (
    _record_query,
    SUBSCRIPTION_QUERY,
    PLAN_QUERY,
    MEMBER_QUERY,
    ATTENDANCE_QUERY,
)

# Centralized Billing SDK and Payment Document model
from app.modules.billing import BillingService
from app.modules.billing.documents.payment_doc import PaymentDoc


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


# ══════════════════════════════════════════════════════════════════════
#  MEMBER SUB-ENTITIES (Membership, Orders, Invoices, Payments, Attendance)
# ══════════════════════════════════════════════════════════════════════

@router.get("/members/{identifier}/membership")
async def get_member_membership(
    identifier: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Retrieve active membership (subscription) details for a member.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    member_id = member["data"].get("member_id")
    if not member_id:
        return ok(data=None, message="Member has no subscription ID.")

    active_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active",
    })

    if active_sub:
        plan_code = active_sub["data"].get("plan_code")
        if plan_code:
            plan_doc = await repo.find_one({**PLAN_QUERY, "data.code": plan_code})
            active_sub["plan_details"] = plan_doc["data"] if plan_doc else None
        else:
            active_sub["plan_details"] = None

    return ok(data=active_sub, message="Active membership retrieved.")


@router.get("/members/{identifier}/orders")
async def get_member_orders(
    identifier: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    List billing orders for a specific gym member.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    actual_member_id = member["data"].get("member_id")
    if not actual_member_id:
        return paginated(
            data=[],
            total=0,
            skip=(page - 1) * limit,
            limit=limit,
            message="Member has no subscription ID.",
        )

    billing = BillingService(db, ctx)
    skip = (page - 1) * limit
    orders, total = await billing.orders.list(
        customer_ref_id=actual_member_id,
        skip=skip,
        limit=limit,
    )

    data = []
    for order in orders:
        data.append({
            "order_number": order.order_number,
            "status": order.status,
            "subtotal": order.subtotal,
            "tax_amount": order.tax_amount,
            "total": order.total,
            "currency": order.currency,
            "invoice_ref": order.invoice_ref,
            "notes": order.notes,
            "created_at": (
                order.meta_info.created.at.isoformat()
                if order.meta_info and order.meta_info.created
                else None
            ),
        })

    return paginated(
        data=data,
        total=total,
        skip=skip,
        limit=limit,
        message="Orders retrieved successfully.",
    )


@router.get("/members/{identifier}/invoices")
async def get_member_invoices(
    identifier: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    List billing invoices for a specific gym member.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    actual_member_id = member["data"].get("member_id")
    if not actual_member_id:
        return paginated(
            data=[],
            total=0,
            skip=(page - 1) * limit,
            limit=limit,
            message="Member has no subscription ID.",
        )

    billing = BillingService(db, ctx)
    skip = (page - 1) * limit
    invoices, total = await billing.invoices.list(
        customer_ref_id=actual_member_id,
        skip=skip,
        limit=limit,
    )

    data = []
    for invoice in invoices:
        data.append({
            "invoice_number": invoice.invoice_number,
            "status": invoice.status,
            "subtotal": invoice.subtotal,
            "tax_amount": (
                invoice.tax_breakdown.total_tax
                if invoice.tax_breakdown
                else 0.0
            ),
            "total": invoice.total,
            "amount_paid": invoice.amount_paid,
            "balance_due": invoice.balance_due,
            "currency": invoice.currency,
            "issue_date": invoice.issue_date,
            "due_date": invoice.due_date,
            "created_at": (
                invoice.meta_info.created.at.isoformat()
                if invoice.meta_info and invoice.meta_info.created
                else None
            ),
        })

    return paginated(
        data=data,
        total=total,
        skip=skip,
        limit=limit,
        message="Invoices retrieved successfully.",
    )


@router.get("/members/{identifier}/payments")
async def get_member_payments(
    identifier: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    List payments for a specific gym member by retrieving their invoices first.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    actual_member_id = member["data"].get("member_id")
    if not actual_member_id:
        return paginated(
            data=[],
            total=0,
            skip=(page - 1) * limit,
            limit=limit,
            message="Member has no subscription ID.",
        )

    billing = BillingService(db, ctx)
    invoices, _ = await billing.invoices.list(
        customer_ref_id=actual_member_id,
        limit=1000,
    )
    invoice_refs = [inv.invoice_number for inv in invoices]

    skip = (page - 1) * limit
    if not invoice_refs:
        return paginated(
            data=[],
            total=0,
            skip=skip,
            limit=limit,
            message="No payments found.",
        )

    query = {"data.invoice_ref": {"$in": invoice_refs}}
    payments = await PaymentDoc.org_find(
        ctx,
        query,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await PaymentDoc.org_count(ctx, query)

    data = []
    for payment in payments:
        data.append({
            "payment_number": payment.payment_number,
            "invoice_ref": payment.invoice_ref,
            "amount": payment.amount,
            "currency": payment.currency,
            "method": payment.method,
            "status": payment.status,
            "payment_date": payment.payment_date,
            "transaction_ref": payment.transaction_ref,
            "notes": payment.notes,
            "created_at": (
                payment.meta_info.created.at.isoformat()
                if payment.meta_info and payment.meta_info.created
                else None
            ),
        })

    return paginated(
        data=data,
        total=total,
        skip=skip,
        limit=limit,
        message="Payments retrieved successfully.",
    )


@router.get("/members/{identifier}/attendance")
async def get_member_attendance(
    identifier: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    List attendance check-ins for a specific gym member.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    actual_member_id = member["data"].get("member_id")
    if not actual_member_id:
        return paginated(
            data=[],
            total=0,
            skip=(page - 1) * limit,
            limit=limit,
            message="Member has no subscription ID.",
        )

    query = {
        **ATTENDANCE_QUERY,
        "data.member_id": actual_member_id,
    }

    skip = (page - 1) * limit
    records = await repo.find(
        query,
        sort=[("_meta.created.at", -1)],
        skip=skip,
        limit=limit,
    )
    total = await repo.count(query)

    data = []
    for r in records:
        r_data = r.get("data", {})
        data.append({
            "timestamp": r_data.get("timestamp"),
            "date": r_data.get("date"),
            "hour": r_data.get("hour"),
            "subscription_id": r_data.get("subscription_id"),
            "has_active_plan": r_data.get("has_active_plan"),
            "created_at": (
                r.get("_meta", {}).get("created", {}).get("at")
            ),
        })

    return paginated(
        data=data,
        total=total,
        skip=skip,
        limit=limit,
        message="Attendance retrieved successfully.",
    )


@router.get("/members/{identifier}/timeline")
async def get_member_timeline(
    identifier: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Aggregate, sort, and paginate chronological activities/events for a member.
    """
    repo = OrgRepository(db, "records", ctx)
    member = await repo.find_one(_record_query(identifier))
    if not member:
        not_found(message=f"Member '{identifier}' not found.")

    actual_member_id = member["data"].get("member_id")
    if not actual_member_id:
        return paginated(
            data=[],
            total=0,
            skip=(page - 1) * limit,
            limit=limit,
            message="Member has no subscription ID.",
        )

    billing = BillingService(db, ctx)

    # 1. Fetch check-ins
    attendance_records = await repo.find(
        {**ATTENDANCE_QUERY, "data.member_id": actual_member_id},
        limit=50,
    )

    # 2. Fetch subscriptions
    subscriptions = await repo.find(
        {**SUBSCRIPTION_QUERY, "data.member_id": actual_member_id},
        limit=50,
    )

    # 3. Fetch orders
    orders, _ = await billing.orders.list(
        customer_ref_id=actual_member_id,
        limit=50,
    )

    # 4. Fetch invoices
    invoices, _ = await billing.invoices.list(
        customer_ref_id=actual_member_id,
        limit=50,
    )
    invoice_refs = [inv.invoice_number for inv in invoices]

    # 5. Fetch payments
    payments = []
    if invoice_refs:
        payments = await PaymentDoc.org_find(
            ctx,
            {"data.invoice_ref": {"$in": invoice_refs}},
            limit=50,
        )

    events = []

    def _format_datetime(val: Any) -> Optional[str]:
        from datetime import datetime
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, str):
            return val
        return None

    # Map attendance
    for r in attendance_records:
        r_data = r.get("data", {})
        created_at = r.get("_meta", {}).get("created", {}).get("at")
        timestamp = r_data.get("timestamp") or created_at
        events.append({
            "id": f"checkin-{r.get('_id')}",
            "type": "checkin",
            "title": "Gym Check-in",
            "description": f"Checked in at the gym at {r_data.get('hour', 0):02d}:00.",
            "timestamp": _format_datetime(timestamp),
            "metadata": {
                "date": r_data.get("date"),
                "hour": r_data.get("hour"),
                "has_active_plan": r_data.get("has_active_plan"),
            },
        })

    # Map subscriptions
    for sub in subscriptions:
        sub_data = sub.get("data", {})
        created_at = sub.get("_meta", {}).get("created", {}).get("at")
        events.append({
            "id": f"subscription-{sub.get('_id')}",
            "type": "subscription",
            "title": f"Subscription {sub_data.get('status', '').capitalize()}",
            "description": f"Enrolled in {sub_data.get('plan_name')} Plan ({sub_data.get('billing_cycle')}).",
            "timestamp": _format_datetime(created_at),
            "metadata": {
                "subscription_id": sub_data.get("subscription_id"),
                "plan_name": sub_data.get("plan_name"),
                "price": sub_data.get("price"),
                "start_date": sub_data.get("start_date"),
                "end_date": sub_data.get("end_date"),
                "is_paid": sub_data.get("is_paid"),
                "status": sub_data.get("status"),
            },
        })

    # Map orders
    for order in orders:
        created_at = (
            order.meta_info.created.at
            if order.meta_info and order.meta_info.created
            else None
        )
        events.append({
            "id": f"order-{order.order_number}",
            "type": "order",
            "title": f"Order {order.status.capitalize()}",
            "description": f"Order {order.order_number} created for {order.total} {order.currency}.",
            "timestamp": _format_datetime(created_at),
            "metadata": {
                "order_number": order.order_number,
                "status": order.status,
                "total": order.total,
                "currency": order.currency,
                "invoice_ref": order.invoice_ref,
            },
        })

    # Map invoices
    for invoice in invoices:
        created_at = (
            invoice.meta_info.created.at
            if invoice.meta_info and invoice.meta_info.created
            else None
        )
        events.append({
            "id": f"invoice-{invoice.invoice_number}",
            "type": "invoice",
            "title": f"Invoice {invoice.status.capitalize()}",
            "description": f"Invoice {invoice.invoice_number} generated for {invoice.total} {invoice.currency}.",
            "timestamp": _format_datetime(created_at),
            "metadata": {
                "invoice_number": invoice.invoice_number,
                "status": invoice.status,
                "total": invoice.total,
                "balance_due": invoice.balance_due,
                "due_date": invoice.due_date,
            },
        })

    # Map payments
    for payment in payments:
        created_at = (
            payment.meta_info.created.at
            if payment.meta_info and payment.meta_info.created
            else None
        )
        events.append({
            "id": f"payment-{payment.payment_number}",
            "type": "payment",
            "title": f"Payment {payment.status.capitalize()}",
            "description": f"Captured payment of {payment.amount} {payment.currency} via {payment.method.upper()}.",
            "timestamp": _format_datetime(created_at),
            "metadata": {
                "payment_number": payment.payment_number,
                "invoice_ref": payment.invoice_ref,
                "amount": payment.amount,
                "method": payment.method,
                "status": payment.status,
                "payment_date": payment.payment_date,
            },
        })

    # Sort events descending by timestamp
    events.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    # Paginate
    skip = (page - 1) * limit
    paginated_events = events[skip : skip + limit]

    return paginated(
        data=paginated_events,
        total=len(events),
        skip=skip,
        limit=limit,
        message="Timeline retrieved successfully.",
    )






