"""
gym/routers/invoices.py — Order-first membership sales flow.

Correct lifecycle (subscription created ONLY after payment confirmed):
    1. POST /membership/create-order            → Order created (pending)
    2. GET  /orders/{order_number}              → Display order to receptionist
    3. POST /orders/{order_number}/confirm      → Confirm order → auto-create invoice
    4. GET  /invoices/{invoice_number}          → Display invoice to receptionist
    5. POST /invoices/{n}/pay                   → Payment + subscription + activation
    6. POST /invoices/{n}/send-link             → Send payment link for later
    7. POST /invoices/{n}/cancel                → Cancel unpaid invoice

Webhook:
    POST /membership/webhook/payment-complete   → External gateway callback

Legacy per-subscription invoice view:
    GET  /membership/{subscription_id}/invoice  → Invoice for an existing sub
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, not_found, bad_request, conflict
from app.core.database import get_db
from app.db.org_sequence import OrgSequenceService
from app.core.utils import sanitize_payload
from app.modules.gym.routers.constants import (
    ENTITY_SUBSCRIPTION,
    ALLOWED_PAYMENT_METHODS,
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    _calculate_end_date,
)

router = APIRouter()
_log = logging.getLogger("app.gym.billing")


# ── Helpers ──────────────────────────────────────────────────────────

def _build_gym_context(
    member_id: str,
    plan_code: str,
    billing_cycle: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Serialize gym-specific metadata into a JSON string for order notes.

    The billing SDK's SourceRefEmbed only carries app/ref_type/ref_id.
    We embed the richer gym context in the order's notes field as a
    structured JSON envelope so downstream steps (confirm, pay) can
    reconstruct the full membership intent.
    """
    return json.dumps({
        "member_id": member_id,
        "plan_code": plan_code,
        "billing_cycle": billing_cycle,
        "start_date": start_date,
        "end_date": end_date,
    })


def _parse_gym_context(notes: str) -> dict:
    """
    Extract gym-specific metadata from order notes.

    Returns an empty dict if parsing fails — caller must validate.
    """
    try:
        return json.loads(notes)
    except (json.JSONDecodeError, TypeError):
        return {}


# ══════════════════════════════════════════════════════════════════════
#  STEP 1 — CREATE ORDER (no subscription, no invoice)
# ══════════════════════════════════════════════════════════════════════

@router.post("/membership/create-order")
async def create_membership_order(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Create a billing ORDER for a gym membership — NO subscription or invoice created.

    This is the first step in the sales flow:
        SelectPlan → ReviewOrder → **create-order** → OrderView

    The order captures billing intent with server-computed pricing + tax.
    Plan price is read from the database — never from the frontend payload.

    Idempotency: If a pending order already exists for this member + plan
    combination, it is returned rather than creating a duplicate.

    Expected payload:
        {
            "member_id":  "M-1",
            "plan_code":  "GYM_PRO",
            "start_date": "2026-06-05"  (optional, defaults to today)
        }

    Returns:
        order_number, subtotal, tax_amount, total, status=pending
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
            {"_meta.id": member_id},
        ],
    })
    if not member_doc:
        not_found(message=f"Member '{member_id}' not found.")

    resolved_member_id = member_doc["data"].get("member_id")

    # ── 2. Verify plan ───────────────────────────────────────────────
    plan_doc = await repo.find_one({
        **PLAN_QUERY,
        "data.code": plan_code,
        "data.is_active": True,
    })
    if not plan_doc:
        not_found(message=f"Active plan with code '{plan_code}' not found.")

    # ── 3. Block if already active ───────────────────────────────────
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

    # ── 4. Calculate dates ───────────────────────────────────────────
    plan_data = plan_doc["data"]
    billing_cycle = plan_data.get("billing_cycle", "monthly")

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    end_date = _calculate_end_date(start_date, billing_cycle)

    # ── 5. Build and create ORDER via billing SDK ────────────────────
    from app.modules.gym.billing_service import GymBillingService
    from app.modules.billing import (
        BillingService,
        CreateOrderInput,
        ServiceLineItem,
        CustomerRefSchema,
    )

    gym_billing = GymBillingService(db, ctx)
    seller_gstin = await gym_billing._get_seller_gstin()

    member_data = member_doc["data"]
    member_name = (
        f"{member_data.get('firstName', '')} "
        f"{member_data.get('lastName', '')}"
    ).strip()

    # Serialize gym context into notes for downstream steps
    gym_context_json = _build_gym_context(
        member_id=resolved_member_id,
        plan_code=plan_code,
        billing_cycle=billing_cycle,
        start_date=start_date,
        end_date=end_date,
    )

    billing = BillingService(db, ctx)
    order_input = CreateOrderInput(
        customer_ref=CustomerRefSchema(
            ref_type="member",
            ref_id=resolved_member_id,
            name=member_name,
            email=member_data.get("email", ""),
            phone=member_data.get("phone", ""),
        ),
        line_items=[
            ServiceLineItem(
                item_type="service",
                description=f"Gym Membership: {plan_data.get('name')} ({billing_cycle})",
                quantity=1,
                unit_price=plan_data.get("price", 0),
                hsn_sac_code="997212",
                tax_category="higher",
                source_item_code=plan_code,
                service_period_start=start_date,
                service_period_end=end_date,
            )
        ],
        seller_gstin=seller_gstin,
        place_of_supply=seller_gstin[:2],
        # Source ref links to member — limited to app/ref_type/ref_id
        source_ref={
            "app": ctx.app_code,
            "ref_type": "membership_intent",
            "ref_id": resolved_member_id,
        },
        # Full gym context stored as structured JSON in notes
        notes=gym_context_json,
    )

    order_doc = await billing.orders.create(order_input)

    return created(
        message="Order created successfully. Review and confirm to generate invoice.",
        data={
            "order_number": order_doc.order_number,
            "member_id": resolved_member_id,
            "member_name": member_name,
            "plan_name": plan_data.get("name"),
            "plan_code": plan_code,
            "billing_cycle": billing_cycle,
            "start_date": start_date,
            "end_date": end_date,
            "subtotal": order_doc.subtotal,
            "tax_amount": order_doc.tax_amount,
            "total": order_doc.total,
            "status": order_doc.status,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 2 — GET ORDER
# ══════════════════════════════════════════════════════════════════════

@router.get("/orders/{order_number:path}")
async def get_gym_order(
    order_number: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Fetch a gym membership order for the OrderView page.

    Returns the order with server-computed pricing, tax, and status.
    The gym context (member_id, plan_code, dates) is extracted from notes.
    """
    from app.modules.billing import BillingService

    billing = BillingService(db, ctx)
    order_doc = await billing.orders.get(order_number)

    if not order_doc:
        not_found(message=f"Order '{order_number}' not found.")

    # Extract gym context from notes
    gym_ctx = _parse_gym_context(order_doc.notes)

    # Build customer_ref safely
    customer_ref = {}
    if order_doc.customer_ref:
        customer_ref = {
            "ref_type": order_doc.customer_ref.ref_type,
            "ref_id": order_doc.customer_ref.ref_id,
            "name": order_doc.customer_ref.name,
            "email": order_doc.customer_ref.email,
            "phone": order_doc.customer_ref.phone,
        }

    # Build line items
    line_items = [
        {
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "tax_amount": li.tax_amount,
            "taxable_amount": li.taxable_amount,
            "line_total": li.line_total,
            "source_item_code": li.source_item_code,
            "hsn_sac_code": li.hsn_sac_code,
            "service_period_start": li.service_period_start,
            "service_period_end": li.service_period_end,
        }
        for li in (order_doc.line_items or [])
    ]

    return ok(
        message="Order retrieved.",
        data={
            "order_number": order_doc.order_number,
            "status": order_doc.status,
            "customer_ref": customer_ref,
            "line_items": line_items,
            "subtotal": order_doc.subtotal,
            "tax_amount": order_doc.tax_amount,
            "total": order_doc.total,
            "currency": order_doc.currency,
            "invoice_ref": order_doc.invoice_ref,
            # Flattened gym context for UI convenience
            "member_id": gym_ctx.get("member_id", ""),
            "plan_code": gym_ctx.get("plan_code", ""),
            "billing_cycle": gym_ctx.get("billing_cycle", ""),
            "start_date": gym_ctx.get("start_date", ""),
            "end_date": gym_ctx.get("end_date", ""),
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 3 — CONFIRM ORDER → AUTO-CREATE INVOICE
# ══════════════════════════════════════════════════════════════════════

@router.post("/orders/{order_number:path}/confirm")
async def confirm_gym_order(
    order_number: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Confirm a pending order — auto-creates a linked invoice.

    This is the transition from OrderView to InvoiceView:
        OrderView → **confirm** → InvoiceView

    The billing SDK handles:
        Order (pending → invoiced)
        Invoice (draft → sent)

    Returns:
        order_number, order_status, invoice_number, invoice_status
    """
    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)
    order_doc, invoice_doc = await gym_billing.confirm_and_invoice(order_number)

    # Extract gym context from order notes so frontend can display it
    gym_ctx = _parse_gym_context(order_doc.notes)

    return ok(
        message="Order confirmed. Invoice generated.",
        data={
            "order_number": order_doc.order_number,
            "order_status": order_doc.status,
            "invoice_number": invoice_doc.invoice_number,
            "invoice_status": invoice_doc.status,
            # Carry gym context forward for the InvoiceView
            "member_id": gym_ctx.get("member_id", ""),
            "plan_code": gym_ctx.get("plan_code", ""),
            "billing_cycle": gym_ctx.get("billing_cycle", ""),
            "start_date": gym_ctx.get("start_date", ""),
            "end_date": gym_ctx.get("end_date", ""),
            "subtotal": invoice_doc.subtotal,
            "tax_amount": invoice_doc.tax_amount if hasattr(invoice_doc, "tax_amount") else 0,
            "total": invoice_doc.total,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 4 — GET INVOICE
# ══════════════════════════════════════════════════════════════════════

@router.get("/invoices/{invoice_number:path}")
async def get_gym_invoice(
    invoice_number: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Fetch a gym membership invoice with full payment history.

    Used by the InvoiceDetails page. Since InvoiceDoc has no source_ref,
    we look up the originating order via OrderDoc.find_by_invoice() to
    reconstruct member/plan context for the UI.
    """
    from app.modules.gym.billing_service import GymBillingService
    from app.modules.billing.documents.order_doc import OrderDoc

    gym_billing = GymBillingService(db, ctx)
    invoice_doc, payments = await gym_billing.get_invoice_with_payments(invoice_number)

    if not invoice_doc:
        not_found(message=f"Invoice '{invoice_number}' not found.")

    payment_history = [
        {
            "payment_number": p.payment_number,
            "amount": p.amount,
            "method": p.method,
            "status": p.status,
            "payment_date": (
                p.payment_date.isoformat()
                if hasattr(p.payment_date, "isoformat")
                else str(p.payment_date)
            ),
            "transaction_ref": p.transaction_ref or "",
        }
        for p in (payments or [])
    ]

    # Look up originating order for gym context
    order_doc = await OrderDoc.find_by_invoice(ctx, invoice_number)
    gym_ctx = _parse_gym_context(order_doc.notes) if order_doc else {}

    # Resolve customer_ref safely — SDK may return dict or object
    raw_customer_ref = getattr(invoice_doc, "customer_ref", {})
    if raw_customer_ref and hasattr(raw_customer_ref, "ref_id"):
        customer_ref = {
            "ref_id": raw_customer_ref.ref_id,
            "name": raw_customer_ref.name,
            "email": raw_customer_ref.email,
            "phone": raw_customer_ref.phone,
        }
    elif isinstance(raw_customer_ref, dict):
        customer_ref = raw_customer_ref
    else:
        customer_ref = {}

    return ok(
        message="Invoice retrieved.",
        data={
            "invoice_number": invoice_doc.invoice_number,
            "status": invoice_doc.status,
            "subtotal": invoice_doc.subtotal,
            "tax_amount": (
                invoice_doc.tax_breakdown.total_tax
                if invoice_doc.tax_breakdown
                else 0
            ),
            "total": invoice_doc.total,
            "amount_paid": invoice_doc.amount_paid,
            "balance_due": invoice_doc.balance_due,
            "currency": getattr(invoice_doc, "currency", "INR"),
            "issue_date": invoice_doc.issue_date,
            "due_date": invoice_doc.due_date,
            "payment_terms": getattr(invoice_doc, "payment_terms", ""),
            "customer_ref": customer_ref,
            "payment_history": payment_history,
            # Gym context from originating order
            "order_number": order_doc.order_number if order_doc else "",
            "member_id": gym_ctx.get("member_id", ""),
            "plan_code": gym_ctx.get("plan_code", ""),
            "billing_cycle": gym_ctx.get("billing_cycle", ""),
            "start_date": gym_ctx.get("start_date", ""),
            "end_date": gym_ctx.get("end_date", ""),
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 5 — PAY INVOICE (atomic: payment + subscription + member)
# ══════════════════════════════════════════════════════════════════════

@router.post("/invoices/{invoice_number:path}/pay")
async def pay_gym_invoice(
    invoice_number: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Pay a gym membership invoice and atomically activate the membership.

    This is the SINGLE write boundary for the entire sales flow:
        1. Record payment against the invoice (billing SDK)
        2. Create the subscription record (entity_type: "subscription")
        3. Update member status → active

    The member/plan context is reconstructed from the originating ORDER
    (looked up via OrderDoc.find_by_invoice), not from the invoice itself.

    Expected payload:
        {
            "payment_method":  "cash",          (required)
            "transaction_ref": "CSH-123456",   (optional)
            "notes":           "Walk-in cash"   (optional)
        }

    Side effects (all via sequential writes):
        Invoice:      sent → paid
        Subscription: [CREATED] status=active, is_paid=True
        Member:       attention/frozen → active
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

    from app.modules.gym.billing_service import GymBillingService
    from app.modules.billing.documents.order_doc import OrderDoc

    gym_billing = GymBillingService(db, ctx)

    # ── 1. Fetch and validate invoice ────────────────────────────────
    invoice_doc, _ = await gym_billing.get_invoice_with_payments(invoice_number)
    if not invoice_doc:
        not_found(message=f"Invoice '{invoice_number}' not found.")
    if invoice_doc.balance_due <= 0:
        bad_request(message="Invoice is already fully paid.")
    if invoice_doc.status == "cancelled":
        bad_request(message="Cannot pay a cancelled invoice.")

    # ── 2. Look up originating ORDER for member/plan context ─────────
    order_doc = await OrderDoc.find_by_invoice(ctx, invoice_number)
    if not order_doc:
        bad_request(
            message=(
                "No originating order found for this invoice. "
                "Cannot create subscription."
            )
        )

    gym_ctx = _parse_gym_context(order_doc.notes)
    member_id = gym_ctx.get("member_id")
    plan_code = gym_ctx.get("plan_code")
    start_date = gym_ctx.get("start_date")
    end_date = gym_ctx.get("end_date")
    billing_cycle = gym_ctx.get("billing_cycle", "monthly")

    if not member_id or not plan_code:
        bad_request(
            message=(
                "Order context is missing member_id or plan_code. "
                "Cannot create subscription."
            )
        )

    repo = OrgRepository(db, "records", ctx)

    # ── 3. Verify member still exists ────────────────────────────────
    member_doc = await repo.find_one({
        **MEMBER_QUERY,
        "$or": [
            {"data.member_id": member_id},
            {"_meta.id": member_id},
        ],
    })
    if not member_doc:
        not_found(message=f"Member '{member_id}' not found.")

    resolved_member_id = member_doc["data"].get("member_id")

    # ── 4. Verify plan still active ──────────────────────────────────
    plan_doc = await repo.find_one({
        **PLAN_QUERY,
        "data.code": plan_code,
        "data.is_active": True,
    })
    if not plan_doc:
        not_found(message=f"Active plan '{plan_code}' not found.")

    # ── 5. Guard: block duplicate active subscription ─────────────────
    active_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": resolved_member_id,
        "data.status": "active",
    })
    if active_sub:
        conflict(
            message=f"Member '{member_id}' already has an active subscription.",
            error_code="ACTIVE_SUBSCRIPTION_EXISTS",
        )

    # ── 6. Record payment ─────────────────────────────────────────────
    payment_doc = await gym_billing.record_payment(
        invoice_number=invoice_number,
        payment_amount=invoice_doc.balance_due,
        payment_method=payment_method,
        transaction_ref=data.get("transaction_ref", ""),
        notes=data.get("notes", f"Membership payment via {payment_method.upper()}"),
    )

    # ── 7. Create subscription record (payment confirmed) ────────────
    plan_data = plan_doc["data"]
    member_data = member_doc["data"]
    member_name = (
        f"{member_data.get('firstName', '')} "
        f"{member_data.get('lastName', '')}"
    ).strip()

    seq = OrgSequenceService(db, ctx)
    subscription_id = await seq.simple("subscription", prefix="SUB")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    effective_start = start_date or today
    effective_end = end_date or _calculate_end_date(effective_start, billing_cycle)

    subscription_data = {
        "member_id": resolved_member_id,
        "member_record_id": member_doc["_meta"]["id"],
        "member_name": member_name,
        "plan_code": plan_code,
        "plan_name": plan_data.get("name", ""),
        "plan_id": plan_doc["_meta"]["id"],
        "price": plan_data.get("price", 0),
        "currency": plan_data.get("currency", "INR"),
        "billing_cycle": billing_cycle,
        "start_date": effective_start,
        "end_date": effective_end,
        "subscription_id": subscription_id,
        # Created as active — payment is already confirmed
        "status": "active",
        "is_paid": True,
        "payment_method": payment_method,
        "payment_amount": invoice_doc.total,
        "invoice_number": invoice_number,
        "order_number": order_doc.order_number,
        "payment_number": payment_doc.payment_number,
        "notes": data.get("notes", ""),
    }

    await repo.insert_one(
        data=subscription_data,
        entity_type=ENTITY_SUBSCRIPTION,
        prefix=ctx.app_code.upper(),
    )

    # ── 8. Activate member ────────────────────────────────────────────
    await repo.update_one(
        {**MEMBER_QUERY, "data.member_id": resolved_member_id},
        {
            "plan": plan_data.get("name", plan_code),
            "plan_code": plan_code,
            "subscription_id": subscription_id,
            "status": "active",
        },
    )

    # ── 9. Reload updated invoice ─────────────────────────────────────
    updated_invoice, _ = await gym_billing.get_invoice_with_payments(invoice_number)

    return ok(
        message="Payment confirmed. Membership activated!",
        data={
            "payment_number": payment_doc.payment_number,
            "payment_method": payment_method,
            "amount_paid": payment_doc.amount,
            "invoice_number": invoice_number,
            "invoice_status": updated_invoice.status,
            "balance_due": updated_invoice.balance_due,
            "is_fully_paid": updated_invoice.balance_due <= 0,
            "order_number": order_doc.order_number,
            "subscription_id": subscription_id,
            "subscription_status": "active",
            "member_id": resolved_member_id,
            "plan_name": plan_data.get("name"),
            "start_date": effective_start,
            "end_date": effective_end,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 6 — SEND PAYMENT LINK
# ══════════════════════════════════════════════════════════════════════

@router.post("/invoices/{invoice_number:path}/send-link")
async def send_gym_invoice_payment_link(
    invoice_number: str,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Generate and dispatch a payment link for a gym membership invoice.

    The subscription is NOT created here — it will be created when the
    customer pays via the link (handled by the webhook endpoint).

    Expected payload:
        {
            "send_via": "email"   (email | sms | both — default: email)
        }
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)
    invoice_doc, _ = await gym_billing.get_invoice_with_payments(invoice_number)

    if not invoice_doc:
        not_found(message=f"Invoice '{invoice_number}' not found.")
    if invoice_doc.balance_due <= 0:
        bad_request(message="Invoice is already fully paid. No link needed.")
    if invoice_doc.status == "cancelled":
        bad_request(message="Cannot send a link for a cancelled invoice.")

    payment_link_url = gym_billing.generate_payment_link_url(
        invoice_number=invoice_number,
        total=invoice_doc.balance_due,
    )

    send_via = data.get("send_via", "email")
    _log.info(
        "Payment link dispatched via %s: invoice=%s url=%s org=%s",
        send_via,
        invoice_number,
        payment_link_url,
        ctx.org_id,
    )

    return ok(
        message=f"Payment link sent via {send_via}.",
        data={
            "payment_link_url": payment_link_url,
            "invoice_number": invoice_number,
            "invoice_status": invoice_doc.status,
            "balance_due": invoice_doc.balance_due,
            "total": invoice_doc.total,
            "send_via": send_via,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  STEP 7 — CANCEL INVOICE
# ══════════════════════════════════════════════════════════════════════

@router.post("/invoices/{invoice_number:path}/cancel")
async def cancel_gym_invoice(
    invoice_number: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Cancel an unpaid gym membership invoice.

    Only invoices in draft or sent status can be cancelled.
    No subscription is written, so this is a safe no-op for the
    membership record.
    """
    from app.modules.gym.billing_service import GymBillingService
    from app.modules.billing import BillingService

    gym_billing = GymBillingService(db, ctx)
    invoice_doc, _ = await gym_billing.get_invoice_with_payments(invoice_number)

    if not invoice_doc:
        not_found(message=f"Invoice '{invoice_number}' not found.")

    if invoice_doc.status not in ("draft", "sent"):
        bad_request(
            message=(
                f"Cannot cancel invoice in status '{invoice_doc.status}'. "
                "Only draft or sent invoices can be cancelled."
            )
        )

    if invoice_doc.balance_due <= 0:
        bad_request(message="Invoice is already fully paid and cannot be cancelled.")

    billing = BillingService(db, ctx)
    await billing.invoices.void(invoice_number)

    return ok(
        message="Invoice cancelled successfully.",
        data={"invoice_number": invoice_number, "status": "cancelled"},
    )


# ══════════════════════════════════════════════════════════════════════
#  WEBHOOK — EXTERNAL PAYMENT CONFIRMATION
# ══════════════════════════════════════════════════════════════════════

@router.post("/membership/webhook/payment-complete")
async def membership_payment_webhook(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Webhook endpoint for external payment confirmation.

    Called by:
        - Razorpay webhook after a payment link is paid
        - Any future payment gateway callback

    Uses the SAME complete_membership_activation() method as direct
    payment — ensuring identical activation logic across all payment paths.

    Expected payload:
        {
            "subscription_id": "SUB-001",
            "invoice_number": "INV/2026-27/0001",
            "payment_method": "upi",
            "transaction_ref": "rzp_pay_xxx",
            "amount": 5900.00,
            "gateway_payment_id": "pay_xxx"
        }
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    subscription_id = data.get("subscription_id")
    invoice_number = data.get("invoice_number")
    payment_method = data.get("payment_method", "online")
    transaction_ref = data.get("transaction_ref", "")
    amount = data.get("amount")

    if not subscription_id or not invoice_number:
        bad_request(message="subscription_id and invoice_number are required.")

    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)

    # 1. Record payment if amount is provided
    if amount and amount > 0:
        await gym_billing.record_payment(
            invoice_number=invoice_number,
            payment_amount=amount,
            payment_method=payment_method,
            transaction_ref=transaction_ref,
            notes=f"Webhook payment: {data.get('gateway_payment_id', '')}",
        )

    # 2. Check if invoice is now fully settled
    updated_invoice, _ = await gym_billing.get_invoice_with_payments(invoice_number)
    is_fully_paid = updated_invoice.balance_due <= 0

    # 3. Activate membership using the shared activation method
    if is_fully_paid:
        await gym_billing.complete_membership_activation(
            subscription_id=subscription_id,
            payment_method=payment_method,
        )

    return ok(
        message="Webhook processed.",
        data={
            "subscription_id": subscription_id,
            "invoice_number": invoice_number,
            "is_fully_paid": is_fully_paid,
            "invoice_status": updated_invoice.status,
            "balance_due": updated_invoice.balance_due,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  LEGACY — GET INVOICE FOR AN EXISTING SUBSCRIPTION
# ══════════════════════════════════════════════════════════════════════

@router.get("/membership/{subscription_id}/invoice")
async def get_membership_invoice(
    subscription_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Get invoice details for a subscription.

    Returns the full invoice with server-computed tax breakdown,
    payment history, and current balance.
    """
    repo = OrgRepository(db, "records", ctx)

    sub_doc = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "$or": [
            {"data.subscription_id": subscription_id},
            {"_meta.id": subscription_id},
        ],
    })
    if not sub_doc:
        not_found(message=f"Subscription '{subscription_id}' not found.")

    invoice_number = sub_doc["data"].get("invoice_number")
    if not invoice_number:
        not_found(message="Subscription has no linked invoice yet. Payment not initiated.")

    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)
    invoice_doc, payments = await gym_billing.get_invoice_with_payments(invoice_number)

    payment_history = [
        {
            "payment_number": p.payment_number,
            "amount": p.amount,
            "method": p.method,
            "status": p.status,
            "payment_date": p.payment_date,
            "transaction_ref": p.transaction_ref,
        }
        for p in payments
    ]

    return ok(
        message="Invoice details retrieved.",
        data={
            "subscription_id": subscription_id,
            "invoice_number": invoice_doc.invoice_number,
            "invoice_type": invoice_doc.invoice_type,
            "subtotal": invoice_doc.subtotal,
            "tax_breakdown": {
                "tax_type": invoice_doc.tax_breakdown.tax_type,
                "tax_rate": invoice_doc.tax_breakdown.tax_rate,
                "taxable_amount": invoice_doc.tax_breakdown.taxable_amount,
                "cgst_rate": invoice_doc.tax_breakdown.cgst_rate,
                "cgst_amount": invoice_doc.tax_breakdown.cgst_amount,
                "sgst_rate": invoice_doc.tax_breakdown.sgst_rate,
                "sgst_amount": invoice_doc.tax_breakdown.sgst_amount,
                "igst_rate": invoice_doc.tax_breakdown.igst_rate,
                "igst_amount": invoice_doc.tax_breakdown.igst_amount,
                "total_tax": invoice_doc.tax_breakdown.total_tax,
                "is_inter_state": invoice_doc.tax_breakdown.is_inter_state,
            },
            "total": invoice_doc.total,
            "amount_paid": invoice_doc.amount_paid,
            "balance_due": invoice_doc.balance_due,
            "currency": invoice_doc.currency,
            "status": invoice_doc.status,
            "issue_date": invoice_doc.issue_date,
            "due_date": invoice_doc.due_date,
            "payment_terms": invoice_doc.payment_terms,
            "payment_history": payment_history,
            "member": {
                "member_id": sub_doc["data"].get("member_id"),
                "member_name": sub_doc["data"].get("member_name"),
            },
            "plan": {
                "plan_code": sub_doc["data"].get("plan_code"),
                "plan_name": sub_doc["data"].get("plan_name"),
                "billing_cycle": sub_doc["data"].get("billing_cycle"),
            },
        },
    )
