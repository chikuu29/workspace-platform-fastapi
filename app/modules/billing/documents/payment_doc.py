"""
PaymentDoc — Beanie document for the payments collection.

Records a payment against an invoice. Supports cash, UPI, card,
net banking, and other manual methods.

Gateway payment fields (gateway_payment_id, gateway_order_id, etc.)
are reserved for future gateway integrations (Razorpay, Stripe, Cashfree).

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_PAYMENT,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.billing.documents.base import BillingDocument


class PaymentDoc(BillingDocument):
    """
    Payment Beanie document — stored in payments collection.

    Linked to an invoice via invoice_ref. Commission fields are
    reserved for future platform-tier gateway payments.

    Usage:
        doc = PaymentDoc.create_for_org(ctx, entity_type=ENTITY_PAYMENT, ...)
        await doc.insert()

        payments = await PaymentDoc.find_by_invoice(ctx, "INV/2026-27/0001")
    """

    # Identity
    payment_number: Indexed(str, unique=True) = ""

    # Invoice linkage
    invoice_ref: str = ""

    # Amount
    amount: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Method
    method: str = PaymentMethod.CASH

    # Gateway details (future — for gateway-mediated payments)
    gateway_provider: str = ""
    gateway_payment_id: str = ""
    gateway_order_id: str = ""
    gateway_signature: str = ""

    # Commission (future — for platform-tier payments)
    commission_rate: float = 0.0
    commission_amount: float = 0.0
    net_to_owner: float = 0.0

    # Status
    status: str = PaymentStatus.CAPTURED

    # Dates
    payment_date: str = ""

    # Reference
    transaction_ref: str = ""
    notes: str = ""

    # Source tracking
    source_app: str = ""

    class Settings:
        name = "payments"
        indexes = [
            # Invoice lookup: find all payments for an invoice
            [("_org.org_id", 1), ("invoice_ref", 1)],
            # Status filtering
            [("_org.org_id", 1), ("status", 1), ("_meta.created.at", -1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, payment_number: str,
    ) -> Optional["PaymentDoc"]:
        """Find a payment by its unique number."""
        return await cls.org_find_one(ctx, {"payment_number": payment_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> List["PaymentDoc"]:
        """Find all payments linked to an invoice."""
        return await cls.org_find(
            ctx,
            {"invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
            limit=100,
        )
