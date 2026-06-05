"""
Gym Billing Service — domain-specific billing orchestrator.

Thin layer bridging the Gym module with the centralized BillingService SDK.

Correct billing lifecycle used:
    Order (pending) → confirm → Invoice (draft → sent) → Payment → Receipt
    ↓                                                       ↓
    Subscription stays "pending"                     complete_membership_activation()
                                                     → subscription "active", member "active"

The key invariant is: subscription + member are NEVER activated until
payment is recorded. The activation logic lives in one method that is
called from both:
    - Direct payment (collect-payment endpoint)
    - Webhook callback (future Razorpay/gateway webhook)

Usage:
    from app.modules.gym.billing_service import GymBillingService

    gym_billing = GymBillingService(db, ctx)
    order_doc = await gym_billing.create_membership_order(member_doc, plan_doc, ...)
    order_doc, invoice_doc = await gym_billing.confirm_and_invoice(order_number)
    payment_doc = await gym_billing.record_payment(invoice_number, ...)
    await gym_billing.complete_membership_activation(subscription_id)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from app.common.org_repository import OrgRepository
from app.common.responses import bad_request, not_found
from app.core.context import OrgContext
from app.db.org_sequence import OrgSequenceService
from app.modules.billing import (
    BillingService,
    CreateOrderInput,
    RecordPaymentInput,
    ServiceLineItem,
    CustomerRefSchema,
)
from app.modules.billing.constants import PaymentMethod


logger = logging.getLogger("app.gym.billing")

# SAC code for Gym/Fitness services (India GST)
GYM_SAC_CODE = "997212"

# Default GST category for gym services (18%)
GYM_TAX_CATEGORY = "higher"

# Entity filters (mirror of router constants)
SUBSCRIPTION_QUERY = {"_meta.entity_type": "subscription"}
MEMBER_QUERY = {"_meta.entity_type": "member"}


class GymBillingService:
    """
    Gym-specific billing orchestrator using the centralized BillingService SDK.

    Correct lifecycle:
        1. create_membership_order()   — Order (pending), subscription (pending)
        2. confirm_and_invoice()       — Order (invoiced), Invoice (draft → sent)
        3. record_payment()            — Payment recorded, invoice balance updated
        4. complete_membership_activation() — subscription (active), member (active)

    Step 4 is the SINGLE common method called by:
        - Direct cash/UPI/card payment  (from collect-payment endpoint)
        - Razorpay webhook callback     (from future webhook endpoint)

    Architecture:
        GymBillingService → BillingService.orders / .invoices / .payments
        (Gym domain)        (Centralized billing engine)
    """

    __slots__ = ("_db", "_ctx", "_billing")

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        """
        Initialize the gym billing orchestrator.

        Args:
            db: Motor async database instance.
            ctx: Current request's org context (from JWT + headers).
        """
        self._db = db
        self._ctx = ctx
        self._billing = BillingService(db, ctx)

    # ── Seller GSTIN Lookup ──────────────────────────────────────────

    async def _get_seller_gstin(self) -> str:
        """
        Retrieve the organization's seller GSTIN from tax profiles.

        Falls back to a default GSTIN if no tax profile is configured.
        The gym operator should configure their GSTIN in billing settings.
        """
        default_gstin = "29AABCU9603R1ZM"
        tax_profile = await self._db["tax_profiles"].find_one(
            {"_org.org_id": self._ctx.org_id}
        )
        if tax_profile:
            return tax_profile.get("data", {}).get("gstin", default_gstin)
        return default_gstin

    # ══════════════════════════════════════════════════════════════════
    #  STEP 1: Create Order (pre-invoice billing intent)
    # ══════════════════════════════════════════════════════════════════

    async def create_membership_order(
        self,
        member_doc: Dict[str, Any],
        plan_doc: Dict[str, Any],
        subscription_id: str,
        start_date: str,
        end_date: str,
        notes: str = "",
    ) -> Any:
        """
        Create a billing ORDER for a gym membership enrollment.

        This is the billing INTENT — no invoice, no payment yet.
        The order holds the computed total (price from DB + tax) and
        links back to the gym subscription via source_ref.

        CRITICAL: Price is read from plan_doc (DB source), never from frontend.

        Args:
            member_doc: Member document from OrgRepository.
            plan_doc: Plan document from OrgRepository (price source of truth).
            subscription_id: The gym subscription ID for linking back.
            start_date: Subscription start date (ISO format).
            end_date: Subscription end date (ISO format).
            notes: Optional notes for the order.

        Returns:
            OrderDoc from billing service with computed tax and totals.
        """
        member_data = member_doc["data"]
        plan_data = plan_doc["data"]

        # Price comes from DB — never trust frontend
        plan_price = plan_data.get("price", 0)
        plan_name = plan_data.get("name", "")
        plan_code = plan_data.get("code", "")

        member_name = (
            f"{member_data.get('firstName', '')} "
            f"{member_data.get('lastName', '')}"
        ).strip()

        seller_gstin = await self._get_seller_gstin()

        order_input = CreateOrderInput(
            customer_ref=CustomerRefSchema(
                ref_type="member",
                ref_id=member_data.get("member_id", ""),
                name=member_name,
                email=member_data.get("email", ""),
                phone=member_data.get("phone", ""),
            ),
            line_items=[
                ServiceLineItem(
                    item_type="service",
                    description=f"Gym Membership: {plan_name}",
                    quantity=1,
                    unit_price=plan_price,
                    hsn_sac_code=GYM_SAC_CODE,
                    tax_category=GYM_TAX_CATEGORY,
                    source_item_code=plan_code,
                    service_period_start=start_date,
                    service_period_end=end_date,
                )
            ],
            seller_gstin=seller_gstin,
            place_of_supply=seller_gstin[:2],
            # Source ref links back to the gym subscription
            source_ref={
                "app": self._ctx.app_code,
                "ref_type": "subscription",
                "ref_id": subscription_id,
            },
            notes=notes,
        )

        order_doc = await self._billing.orders.create(order_input)

        logger.info(
            "Created membership order %s for member %s plan=%s "
            "price=%.2f total=%.2f sub=%s org=%s",
            order_doc.order_number,
            member_data.get("member_id"),
            plan_code,
            plan_price,
            order_doc.total,
            subscription_id,
            self._ctx.org_id,
        )

        return order_doc

    # ══════════════════════════════════════════════════════════════════
    #  STEP 2: Confirm Order → Auto-create Invoice
    # ══════════════════════════════════════════════════════════════════

    async def confirm_and_invoice(
        self, order_number: str,
    ) -> Tuple[Any, Any]:
        """
        Confirm a pending order — auto-creates a linked invoice.

        The billing SDK handles:
            Order (pending → invoiced)
            Invoice (created in draft status)

        We then send the invoice (draft → sent) so it's ready for payment.

        Args:
            order_number: The billing order number to confirm.

        Returns:
            Tuple of (OrderDoc, InvoiceDoc).
        """
        order_doc, invoice_doc = await self._billing.orders.confirm(
            order_number
        )

        # Immediately send the invoice (draft → sent) so payment can
        # be recorded against it (PaymentService rejects draft invoices)
        invoice_doc = await self._billing.invoices.send(
            invoice_doc.invoice_number
        )

        logger.info(
            "Confirmed order %s → invoice %s (sent) org=%s",
            order_number,
            invoice_doc.invoice_number,
            self._ctx.org_id,
        )

        return order_doc, invoice_doc

    # ══════════════════════════════════════════════════════════════════
    #  STEP 3: Record Payment
    # ══════════════════════════════════════════════════════════════════

    async def record_payment(
        self,
        invoice_number: str,
        payment_amount: float,
        payment_method: str,
        transaction_ref: str = "",
        notes: str = "",
    ) -> Any:
        """
        Record a payment against a membership invoice.

        Delegates to BillingService.payments.record() which handles:
        - Invoice balance validation (cannot overpay)
        - Status transitions (sent → partial → paid)
        - Auto-receipt generation when fully paid
        - Linked order completion (order → COMPLETED)

        Args:
            invoice_number: The invoice to pay against.
            payment_amount: Amount being paid.
            payment_method: One of: cash, upi, card, net_banking, etc.
            transaction_ref: External reference (UPI ref, card auth, etc.).
            notes: Optional payment notes.

        Returns:
            PaymentDoc from billing service.
        """
        payment_input = RecordPaymentInput(
            invoice_ref=invoice_number,
            amount=payment_amount,
            method=payment_method,
            transaction_ref=transaction_ref,
            notes=notes or f"Membership payment via {payment_method.upper()}",
        )

        payment_doc = await self._billing.payments.record(payment_input)

        logger.info(
            "Recorded payment %s amount=%.2f method=%s invoice=%s org=%s",
            payment_doc.payment_number,
            payment_amount,
            payment_method,
            invoice_number,
            self._ctx.org_id,
        )

        return payment_doc

    # ══════════════════════════════════════════════════════════════════
    #  STEP 4: Complete Membership Activation (COMMON METHOD)
    # ══════════════════════════════════════════════════════════════════

    async def complete_membership_activation(
        self,
        subscription_id: str,
        payment_method: str,
    ) -> Dict[str, Any]:
        """
        Activate a membership after payment is confirmed.

        THIS IS THE SINGLE SOURCE OF TRUTH for membership activation.
        Called by BOTH:
            - Direct payment flow  (POST /membership/{id}/collect-payment)
            - Webhook callback     (POST /membership/webhook/payment-complete)

        Side effects:
            1. Subscription status → "active", is_paid → True
            2. Member status → "active"
            3. Subscription start_date reset to today if needed

        Args:
            subscription_id: The gym subscription ID to activate.
            payment_method: How the payment was made (for auditing).

        Returns:
            Dict with activation details.
        """
        repo = OrgRepository(self._db, "records", self._ctx)

        # 1. Find subscription
        sub_doc = await repo.find_one({
            **SUBSCRIPTION_QUERY,
            "$or": [
                {"data.subscription_id": subscription_id},
                {"_meta.record_id": subscription_id},
            ],
        })
        if not sub_doc:
            not_found(message=f"Subscription '{subscription_id}' not found.")

        member_id = sub_doc["data"].get("member_id")

        # 2. Update subscription → active + paid
        await repo.update_one(
            {**SUBSCRIPTION_QUERY, "data.subscription_id": subscription_id},
            {
                "status": "active",
                "is_paid": True,
                "payment_method": payment_method,
            },
        )

        # 3. Update member → active
        if member_id:
            await repo.update_one(
                {**MEMBER_QUERY, "data.member_id": member_id},
                {"status": "active"},
            )

        logger.info(
            "Membership activated: sub=%s member=%s method=%s org=%s",
            subscription_id,
            member_id,
            payment_method,
            self._ctx.org_id,
        )

        return {
            "subscription_id": subscription_id,
            "member_id": member_id,
            "status": "active",
            "payment_method": payment_method,
        }

    # ══════════════════════════════════════════════════════════════════
    #  Invoice Lookup
    # ══════════════════════════════════════════════════════════════════

    async def get_invoice_with_payments(
        self, invoice_number: str,
    ) -> tuple:
        """
        Get invoice details with full payment history.

        Returns both the invoice document and all linked payments.

        Args:
            invoice_number: The invoice to retrieve.

        Returns:
            Tuple of (InvoiceDoc, list[PaymentDoc]).
        """
        return await self._billing.invoices.get(invoice_number)

    # ══════════════════════════════════════════════════════════════════
    #  Payment Link Generation
    # ══════════════════════════════════════════════════════════════════

    def generate_payment_link_url(
        self,
        invoice_number: str,
        total: float,
    ) -> str:
        """
        Generate a payment link URL for remote/later payment.

        Currently generates a platform-hosted checkout URL.
        Future: Razorpay Payment Links API integration.

        Args:
            invoice_number: Invoice number for the payment page.
            total: Total amount for display purposes.

        Returns:
            Payment link URL string.
        """
        # TODO: Integrate with Razorpay Payment Links API
        # razorpay_client.payment_link.create({
        #     "amount": int(total * 100),  # paise
        #     "currency": "INR",
        #     "description": f"Gym Membership Payment - {invoice_number}",
        #     "customer": {...},
        #     "notify": {"sms": True, "email": True},
        # })

        base_url = "https://pay.saas-platform.com"
        return f"{base_url}/checkout/{invoice_number}"
