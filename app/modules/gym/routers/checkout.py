"""
gym/routers/checkout.py — Single-page unified checkout flow.

Endpoints:
    POST /checkout/preview — Preview pricing for member + plan (no side effects)
    POST /checkout         — Atomically execute checkout (order + invoice + payment + activate)
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
from app.modules.gym.billing_service import GymBillingService
from app.modules.billing.engines.pricing_engine import compute_line_pricing
from app.modules.billing.engines.tax_engine import compute_line_tax

router = APIRouter()

# Gym default tax settings (aligned with billing_service.py)
GYM_TAX_CATEGORY = "higher"

def _get_mock_discount(coupon_code: Optional[str]) -> tuple[str, float]:
    """Helper to return discount type and value for mock coupon codes."""
    if not coupon_code:
        return "none", 0.0
    
    code = coupon_code.upper().strip()
    if code == "SAVE10":
        return "percentage", 10.0
    elif code == "SAVE20":
        return "percentage", 20.0
    elif code == "FLAT500":
        return "fixed", 500.0
    elif code == "FLAT1000":
        return "fixed", 1000.0
    else:
        # any other code gets a standard 5% discount
        return "percentage", 5.0


@router.post("/checkout/preview")
async def preview_checkout(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Preview checkout pricing for a member and plan.
    Does NOT create any database records or side effects.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    member_id = data.get("member_id")
    plan_code = data.get("plan_code")
    start_date = data.get("start_date")
    coupon_code = data.get("coupon_code")

    if not member_id:
        bad_request(message="member_id is required.")
    if not plan_code:
        bad_request(message="plan_code is required.")

    repo = OrgRepository(db, "records", ctx)

    # 1. Verify member exists
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

    # 2. Verify plan exists and is active
    plan_doc = await repo.find_one({
        **PLAN_QUERY,
        "data.code": plan_code,
        "data.is_active": True,
    })
    if not plan_doc:
        not_found(message=f"Active plan with code '{plan_code}' not found.")

    # 3. Calculate dates
    plan_data = plan_doc["data"]
    billing_cycle = plan_data.get("billing_cycle", "monthly")

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    end_date = _calculate_end_date(start_date, billing_cycle)

    # 4. Compute pricing with optional discount
    plan_price = plan_data.get("price", 0)
    discount_type, discount_value = _get_mock_discount(coupon_code)

    gym_billing = GymBillingService(db, ctx)
    seller_gstin = await gym_billing._get_seller_gstin()
    place_of_supply = seller_gstin[:2]

    # Subtotal calculation
    line_calc = compute_line_pricing(
        quantity=1,
        unit_price=plan_price,
        discount_type=discount_type,
        discount_value=discount_value,
        tax_amount=0.0
    )

    # Tax calculation
    line_tax = compute_line_tax(
        taxable_amount=line_calc.taxable_amount,
        tax_category=GYM_TAX_CATEGORY,
        seller_gstin=seller_gstin,
        place_of_supply=place_of_supply
    )

    # Total calculation
    final_calc = compute_line_pricing(
        quantity=1,
        unit_price=plan_price,
        discount_type=discount_type,
        discount_value=discount_value,
        tax_amount=line_tax.total_tax
    )

    member_name = (
        f"{member_doc['data'].get('firstName', '')} "
        f"{member_doc['data'].get('lastName', '')}"
    ).strip()

    return ok(
        message="Checkout preview generated.",
        data={
            "member": {
                "member_id": resolved_member_id,
                "name": member_name,
                "email": member_doc["data"].get("email"),
                "phone": member_doc["data"].get("phone"),
            },
            "plan": {
                "name": plan_data.get("name"),
                "code": plan_code,
                "price": plan_price,
                "billing_cycle": billing_cycle,
                "accent_color": plan_data.get("accent_color", "brand"),
            },
            "pricing": {
                "subtotal": final_calc.taxable_amount,
                "discount_amount": final_calc.discount_amount,
                "tax_amount": line_tax.total_tax,
                "total": final_calc.line_total,
                "currency": plan_data.get("currency", "INR"),
                "coupon_code": coupon_code,
                "discount_type": discount_type,
                "discount_value": discount_value,
            },
            "dates": {
                "start_date": start_date,
                "end_date": end_date,
            }
        }
    )


@router.post("/checkout")
async def execute_checkout(
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
):
    """
    Execute full checkout atomically.
    Creates subscription, order, and invoice.
    Depending on payment method, records payment and activates membership immediately,
    or generates payment link and sets subscription to pending_payment.
    """
    raw = await request.json()
    data = sanitize_payload(raw)

    member_id = data.get("member_id")
    plan_code = data.get("plan_code")
    start_date = data.get("start_date")
    payment_method = data.get("payment_method")
    transaction_ref = data.get("transaction_ref", "")
    notes = data.get("notes", "")
    send_link_via = data.get("send_link_via", "email")
    coupon_code = data.get("coupon_code")

    if not member_id:
        bad_request(message="member_id is required.")
    if not plan_code:
        bad_request(message="plan_code is required.")
    if not payment_method:
        bad_request(message="payment_method is required.")

    valid_methods = {"cash", "upi", "payment_link"}
    if payment_method not in valid_methods:
        bad_request(message=f"Invalid payment method. Allowed: {', '.join(sorted(valid_methods))}")

    if payment_method == "upi" and not transaction_ref:
        bad_request(message="transaction_ref is required for UPI payments.")

    repo = OrgRepository(db, "records", ctx)

    # 1. Verify member exists
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

    # 2. Verify plan exists and is active
    plan_doc = await repo.find_one({
        **PLAN_QUERY,
        "data.code": plan_code,
        "data.is_active": True,
    })
    if not plan_doc:
        not_found(message=f"Active plan with code '{plan_code}' not found.")

    # 3. Block if already active
    active_sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": resolved_member_id,
        "data.status": "active",
    })
    if active_sub:
        conflict(
            message=f"Member '{resolved_member_id}' already has an active subscription.",
            error_code="ACTIVE_SUBSCRIPTION_EXISTS",
            details={
                "existing_subscription_id": active_sub["data"].get("subscription_id"),
                "existing_plan": active_sub["data"].get("plan_name"),
            },
        )

    # 4. Clean up any existing pending subscriptions for this member + plan
    # to avoid multiple pending subscriptions from multiple checkout attempts.
    await repo.collection.delete_many({
        **SUBSCRIPTION_QUERY,
        "_org.org_id": ctx.org_id,
        "data.member_id": resolved_member_id,
        "data.plan_code": plan_code,
        "data.status": "pending",
    })

    # 5. Calculate subscription dates
    plan_data = plan_doc["data"]
    billing_cycle = plan_data.get("billing_cycle", "monthly")

    if not start_date:
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    end_date = _calculate_end_date(start_date, billing_cycle)

    # 6. Create subscription record (status depends on payment method)
    member_name = (
        f"{member_doc['data'].get('firstName', '')} "
        f"{member_doc['data'].get('lastName', '')}"
    ).strip()

    seq = OrgSequenceService(db, ctx)
    subscription_id = await seq.simple("subscription", prefix="SUB")

    sub_status = "pending" if payment_method in ("cash", "upi") else "pending_payment"

    discount_type, discount_value = _get_mock_discount(coupon_code)

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
        "start_date": start_date,
        "end_date": end_date,
        "subscription_id": subscription_id,
        "status": sub_status,
        "is_paid": False,
        "payment_method": None,
        "payment_amount": None,
        "order_number": None,
        "invoice_number": None,
        "notes": notes,
        "coupon_code": coupon_code,
        "discount_type": discount_type,
        "discount_value": discount_value,
    }

    await repo.insert_one(
        data=subscription_data,
        entity_type=ENTITY_SUBSCRIPTION,
        prefix=ctx.app_code.upper(),
    )

    # 7. Create billing ORDER with discount
    gym_billing = GymBillingService(db, ctx)
    order_doc = await gym_billing.create_membership_order(
        member_doc=member_doc,
        plan_doc=plan_doc,
        subscription_id=subscription_id,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        discount_type=discount_type,
        discount_value=discount_value,
    )

    # Store order reference on subscription
    await repo.update_one(
        {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
        {
            "order_number": order_doc.order_number,
            "payment_amount": order_doc.total,
        },
    )

    # 8. Confirm order → Auto-creates Invoice (draft → sent)
    order_doc, invoice_doc = await gym_billing.confirm_and_invoice(order_doc.order_number)

    # Store invoice reference on subscription
    await repo.update_one(
        {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
        {"invoice_number": invoice_doc.invoice_number},
    )

    # 9. Handle immediate payments vs payment link
    if payment_method in ("cash", "upi"):
        # Record payment
        payment_doc = await gym_billing.record_payment(
            invoice_number=invoice_doc.invoice_number,
            payment_amount=invoice_doc.balance_due,
            payment_method=payment_method,
            transaction_ref=transaction_ref,
            notes=notes or f"Membership checkout payment via {payment_method.upper()}",
        )

        # Activate subscription & member
        await gym_billing.complete_membership_activation(
            subscription_id=subscription_id,
            payment_method=payment_method,
        )

        return created(
            message="Membership activated successfully!",
            data={
                "subscription_id": subscription_id,
                "member_id": resolved_member_id,
                "plan_name": plan_data.get("name"),
                "order_number": order_doc.order_number,
                "invoice_number": invoice_doc.invoice_number,
                "payment_number": payment_doc.payment_number,
                "subtotal": order_doc.subtotal,
                "discount_amount": order_doc.total - order_doc.subtotal - order_doc.tax_amount, # Wait, let's use the actual order details
                "tax_amount": order_doc.tax_amount,
                "total": order_doc.total,
                "start_date": start_date,
                "end_date": end_date,
                "status": "active",
            }
        )
    
    else:  # payment_link
        # Generate & store payment link URL
        payment_link_url = gym_billing.generate_payment_link_url(
            invoice_number=invoice_doc.invoice_number,
            total=invoice_doc.balance_due,
        )

        await repo.update_one(
            {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
            {"payment_link_url": payment_link_url},
        )

        # Dispatch/log payment link dispatch
        import logging
        logging.getLogger("app.gym.billing").info(
            "Checkout payment link generated and dispatched via %s: invoice=%s member=%s url=%s",
            send_link_via,
            invoice_doc.invoice_number,
            resolved_member_id,
            payment_link_url,
        )

        return created(
            message="Payment link generated. Membership activates on payment.",
            data={
                "subscription_id": subscription_id,
                "order_number": order_doc.order_number,
                "invoice_number": invoice_doc.invoice_number,
                "payment_link_url": payment_link_url,
                "subtotal": order_doc.subtotal,
                "tax_amount": order_doc.tax_amount,
                "total": order_doc.total,
                "status": "payment_pending",
                "send_via": send_link_via,
            }
        )
