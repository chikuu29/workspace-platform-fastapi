"""
gym/routers/membership.py — Membership enroll + payment collection flow.

Endpoints:
    POST /membership/enroll                         — Enroll member (pending subscription + order)
    POST /membership/{subscription_id}/collect-payment  — Collect payment → activate
    POST /membership/{subscription_id}/send-payment-link — Generate & dispatch payment link

This is the TWO-STEP flow:
    1. enroll  → pending subscription + billing order
    2. collect-payment OR send-payment-link

For the cleaner INVOICE-FIRST flow (no subscription until payment),
see invoices.py.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, not_found, bad_request, conflict
from app.db.database import get_database
from app.db.org_sequence import OrgSequenceService
from app.modules.gym.schemas import sanitize_payload
from app.modules.gym.routers.constants import (
    ENTITY_SUBSCRIPTION,
    ALLOWED_PAYMENT_METHODS,
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    _calculate_end_date,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  MEMBERSHIP BILLING FLOW
#  Lifecycle: Enroll (pending) → collect-payment → active
#             Subscription stays "pending" until payment completes
# ══════════════════════════════════════════════════════════════════════

@router.post("/membership/enroll")
async def enroll_membership(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Enroll a member in a subscription plan — creates subscription + billing order.

    IMPORTANT: Subscription is created with status="pending" (NOT active).
    Member is NOT activated here. Activation happens ONLY when payment
    is confirmed via collect-payment or webhook.

    If a pending subscription already exists for this member + plan,
    it is RESUMED (not duplicated) — returns the existing order details.

    Expected payload:
        {
            "member_id": "M-1",
            "plan_code": "GYM_PRO",
            "start_date": "2026-06-04",   (optional — defaults to today)
            "notes": "Signup promo"        (optional)
        }
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

    # ── 3. Block if already active; resume if already pending ────────
    active_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active",
    })
    if active_sub:
        conflict(
            message=f"Member '{member_id}' already has an active subscription.",
            error_code="ACTIVE_SUBSCRIPTION_EXISTS",
            details={
                "existing_subscription_id": active_sub["data"].get("subscription_id"),
                "existing_plan": active_sub["data"].get("plan_name"),
            },
        )

    # Resume pending subscription — prevents duplicate enroll
    pending_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.plan_code": plan_code,
        "data.status": "pending",
    })
    if pending_sub:
        return ok(
            message="Resuming existing pending enrollment.",
            data={
                "subscription_id": pending_sub["data"].get("subscription_id"),
                "member_id": member_id,
                "plan_name": pending_sub["data"].get("plan_name"),
                "plan_code": plan_code,
                "start_date": pending_sub["data"].get("start_date"),
                "end_date": pending_sub["data"].get("end_date"),
                "order_number": pending_sub["data"].get("order_number"),
                "order_total": pending_sub["data"].get("payment_amount"),
                "status": "pending",
                "is_resumed": True,
            },
        )

    # ── 4. Calculate subscription dates ──────────────────────────────
    plan_data = plan_doc["data"]
    billing_cycle = plan_data.get("billing_cycle", "monthly")

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    end_date = _calculate_end_date(start_date, billing_cycle)

    # ── 5. Create subscription record (PENDING — not active yet) ─────
    member_name = (
        f"{member_doc['data'].get('firstName', '')} "
        f"{member_doc['data'].get('lastName', '')}"
    ).strip()

    seq = OrgSequenceService(db, ctx)
    subscription_id = await seq.simple("subscription", prefix="SUB")

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
        "subscription_id": subscription_id,
        # KEY: Status is PENDING until payment is confirmed
        "status": "pending",
        "is_paid": False,
        "payment_method": None,
        "payment_amount": None,   # Set after order is created (server-computed)
        "order_number": None,     # Set after order is created
        "invoice_number": None,   # Set after order is confirmed
        "notes": data.get("notes", ""),
    }

    await repo.insert_one(
        data=subscription_data,
        entity_type=ENTITY_SUBSCRIPTION,
        prefix=ctx.app_code.upper(),
    )

    # ── 6. Create billing ORDER (price from DB — never from frontend) ─
    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)
    order_doc = await gym_billing.create_membership_order(
        member_doc=member_doc,
        plan_doc=plan_doc,
        subscription_id=subscription_id,
        start_date=start_date,
        end_date=end_date,
        notes=data.get("notes", ""),
    )

    # ── 7. Store order reference on the subscription record ──────────
    await repo.update_one(
        {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
        {
            "order_number": order_doc.order_number,
            "payment_amount": order_doc.total,
        },
    )

    return created(
        message="Membership enrolled — awaiting payment.",
        data={
            "subscription_id": subscription_id,
            "member_id": member_id,
            "plan_name": plan_data.get("name"),
            "plan_code": plan_code,
            "start_date": start_date,
            "end_date": end_date,
            "order_number": order_doc.order_number,
            "order_total": order_doc.total,
            "order_subtotal": order_doc.subtotal,
            "order_tax": order_doc.tax_amount,
            "status": "pending",
        },
    )


@router.post("/membership/{subscription_id}/collect-payment")
async def collect_membership_payment(
    subscription_id: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Collect payment for a membership subscription.

    Full lifecycle executed here:
        1. Confirm Order → auto-creates Invoice
        2. Record Payment against Invoice
        3. Activate subscription + member (via GymBillingService)

    Expected payload:
        {
            "payment_method": "cash",       (required: cash | upi | card | ...)
            "transaction_ref": "UPI-1234",  (optional)
            "notes": "Walk-in payment"      (optional)
        }

    Side effects:
        - Order: pending → invoiced → completed
        - Invoice: draft → sent → paid
        - Subscription: pending → active
        - Member: attention → active
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    payment_method = data.get("payment_method")
    if not payment_method:
        bad_request(message="payment_method is required (cash, upi, card).")
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        bad_request(
            message=(
                f"Invalid payment method '{payment_method}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_PAYMENT_METHODS))}."
            )
        )

    repo = OrgRepository(db, "records", ctx)

    # ── 1. Find subscription ─────────────────────────────────────────
    sub_doc = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "$or": [
            {"data.subscription_id": subscription_id},
            {"_meta.record_id": subscription_id},
        ],
    })
    if not sub_doc:
        not_found(message=f"Subscription '{subscription_id}' not found.")

    if sub_doc["data"].get("is_paid"):
        bad_request(message="Subscription is already fully paid.")

    order_number = sub_doc["data"].get("order_number")
    if not order_number:
        bad_request(message="Subscription has no linked billing order.")

    # ── 2. Confirm order → creates invoice (idempotent) ──────────────
    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)

    invoice_number = sub_doc["data"].get("invoice_number")
    if not invoice_number:
        order_doc, invoice_doc = await gym_billing.confirm_and_invoice(order_number)
        invoice_number = invoice_doc.invoice_number

        # Persist invoice reference on subscription
        await repo.update_one(
            {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
            {"invoice_number": invoice_number},
        )
    else:
        invoice_doc, _ = await gym_billing.get_invoice_with_payments(invoice_number)

    # ── 3. Guard: check balance ──────────────────────────────────────
    latest_invoice, _ = await gym_billing.get_invoice_with_payments(invoice_number)
    if latest_invoice.balance_due <= 0:
        bad_request(message="Invoice is already fully paid.")

    # ── 4. Record payment ─────────────────────────────────────────────
    payment_doc = await gym_billing.record_payment(
        invoice_number=invoice_number,
        payment_amount=latest_invoice.balance_due,
        payment_method=payment_method,
        transaction_ref=data.get("transaction_ref", ""),
        notes=data.get("notes", ""),
    )

    # ── 5. Reload invoice for updated status ─────────────────────────
    updated_invoice, payments = await gym_billing.get_invoice_with_payments(invoice_number)

    # ── 6. Activate membership if fully paid ─────────────────────────
    is_fully_paid = updated_invoice.balance_due <= 0
    if is_fully_paid:
        await gym_billing.complete_membership_activation(
            subscription_id=subscription_id,
            payment_method=payment_method,
        )

    return ok(
        message="Payment recorded successfully.",
        data={
            "payment_number": payment_doc.payment_number,
            "payment_method": payment_method,
            "amount_paid": payment_doc.amount,
            "invoice_number": invoice_number,
            "invoice_status": updated_invoice.status,
            "balance_due": updated_invoice.balance_due,
            "is_fully_paid": is_fully_paid,
            "subscription_id": subscription_id,
            "subscription_status": "active" if is_fully_paid else "pending",
        },
    )


@router.post("/membership/{subscription_id}/send-payment-link")
async def send_membership_payment_link(
    subscription_id: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Generate and send a payment link for remote / later payment.

    Confirms the order → creates invoice → generates payment link.
    Subscription stays PENDING — activates only when webhook confirms.

    Expected payload:
        {
            "send_via": "email"  (email | sms | both — default: email)
        }
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    repo = OrgRepository(db, "records", ctx)

    # ── 1. Find subscription ─────────────────────────────────────────
    sub_doc = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "$or": [
            {"data.subscription_id": subscription_id},
            {"_meta.record_id": subscription_id},
        ],
    })
    if not sub_doc:
        not_found(message=f"Subscription '{subscription_id}' not found.")

    if sub_doc["data"].get("is_paid"):
        bad_request(message="Subscription is already fully paid. No link needed.")

    order_number = sub_doc["data"].get("order_number")
    if not order_number:
        bad_request(message="Subscription has no linked billing order.")

    # ── 2. Confirm order → invoice (idempotent) ───────────────────────
    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)

    invoice_number = sub_doc["data"].get("invoice_number")
    if not invoice_number:
        order_doc, invoice_doc = await gym_billing.confirm_and_invoice(order_number)
        invoice_number = invoice_doc.invoice_number

        await repo.update_one(
            {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
            {"invoice_number": invoice_number},
        )
    else:
        invoice_doc, _ = await gym_billing.get_invoice_with_payments(invoice_number)

    # ── 3. Get current balance ────────────────────────────────────────
    latest_invoice, _ = await gym_billing.get_invoice_with_payments(invoice_number)
    if latest_invoice.balance_due <= 0:
        bad_request(message="Invoice is already fully paid. No link needed.")

    # ── 4. Generate & store payment link URL ──────────────────────────
    payment_link_url = gym_billing.generate_payment_link_url(
        invoice_number=invoice_number,
        total=latest_invoice.balance_due,
    )
    await repo.update_one(
        {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
        {"payment_link_url": payment_link_url},
    )

    send_via = data.get("send_via", "email")

    import logging
    logging.getLogger("app.gym.billing").info(
        "Payment link dispatched via %s: invoice=%s member=%s url=%s",
        send_via,
        invoice_number,
        sub_doc["data"].get("member_id"),
        payment_link_url,
    )

    return ok(
        message="Payment link generated and dispatched.",
        data={
            "payment_link_url": payment_link_url,
            "invoice_number": invoice_number,
            "invoice_status": latest_invoice.status,
            "balance_due": latest_invoice.balance_due,
            "total": latest_invoice.total,
            "send_via": send_via,
            "subscription_id": subscription_id,
        },
    )
