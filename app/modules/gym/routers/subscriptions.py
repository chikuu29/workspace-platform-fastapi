"""
gym/routers/subscriptions.py — Legacy direct-activation subscription flow.

Endpoints:
    POST /subscriptions/activate — Directly links a member to a plan,
                                   creates the invoice, and optionally
                                   records payment in one step.

NOTE: This is the original "activate" endpoint kept for backward
compatibility.  New integrations should use the invoice-first flow
in membership.py / invoices.py.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok, created, not_found, bad_request, conflict
from app.core.database import get_db
from app.db.org_sequence import OrgSequenceService
from app.modules.gym.schemas import sanitize_payload
from app.modules.gym.routers.constants import (
    ENTITY_SUBSCRIPTION,
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    _calculate_end_date,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  LEGACY: SUBSCRIPTION ACTIVATION
# ══════════════════════════════════════════════════════════════════════

@router.post("/subscriptions/activate")
async def activate_subscription(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
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

    # ── 3. Block if member already has an active subscription ────────
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
    member_name = (
        f"{member_doc['data'].get('firstName', '')} "
        f"{member_doc['data'].get('lastName', '')}"
    ).strip()

    # Resolve seller GSTIN from org tax profile (fallback to placeholder)
    seller_gstin = "29AABCU9603R1ZM"
    tax_profile = await db["tax_profiles"].find_one({"_org.org_id": ctx.org_id})
    if tax_profile:
        seller_gstin = tax_profile.get("data", {}).get("gstin", seller_gstin)

    from app.modules.billing import (
        BillingService,
        CreateInvoiceInput,
        ServiceLineItem,
        CustomerRefSchema,
        RecordPaymentInput,
    )

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
                hsn_sac_code="997212",    # Gym/Fitness SAC code
                tax_category="higher",    # 18% standard GST
                source_item_code=plan_code,
            )
        ],
        seller_gstin=seller_gstin,
        place_of_supply=seller_gstin[:2],
        due_date=end_date,
        notes=data.get("notes", ""),
    )

    billing = BillingService(db, ctx)
    invoice_doc = await billing.invoices.create(billing_input)

    # ── 6. Optionally record immediate payment ────────────────────────
    is_paid = data.get("is_paid", False)
    payment_method = data.get("payment_method", "cash")
    transaction_ref = data.get("transaction_ref", "")

    if is_paid:
        payment_input = RecordPaymentInput(
            invoice_ref=invoice_doc.invoice_number,
            amount=invoice_doc.total,
            method=payment_method,
            transaction_ref=transaction_ref,
            notes=f"Upfront subscription payment via {payment_method.upper()}",
        )
        await billing.payments.record(payment_input)

        # Reload updated invoice after payment recording
        invoice_doc_tuple = await billing.invoices.get(invoice_doc.invoice_number)
        invoice_doc = invoice_doc_tuple[0]
    else:
        if payment_method == "payment_link":
            import logging
            logging.getLogger("app").info(
                "Payment Link Dispatch: Secure link created for Invoice %s "
                "and sent to customer email %s",
                invoice_doc.invoice_number,
                member_doc["data"].get("email", "N/A"),
            )
            invoice_doc = await billing.invoices.send(invoice_doc.invoice_number)

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
    await repo.update_one(
        {**MEMBER_QUERY, "data.member_id": member_id},
        {
            "plan": plan_data.get("name", plan_code),
            "plan_code": plan_code,
            "subscription_id": subscription_id,
            "status": "active",
        },
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
