"""
PaymentDoc — Beanie document for the payments collection.

Records a payment against an invoice. Supports cash, UPI, card,
net banking, gateway, and other methods. For gateway-mediated payments,
tracks gateway tier (owner vs platform), gateway IDs, and commission.

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
    GatewayProvider,
    GatewayTier,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.billing.documents.base import BillingDocument


class PaymentDoc(BillingDocument):
    """
    Payment Beanie document — stored in payments collection.

    Linked to an invoice via invoice_ref. Commission fields are only
    populated for platform-tier (Tier 2) payments.

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

    # Gateway details (only for gateway-mediated payments)
    gateway_tier: str = ""
    gateway_provider: str = ""
    gateway_payment_id: str = ""
    gateway_order_id: str = ""
    gateway_signature: str = ""

    # Commission (only for platform-tier payments)
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

    class Settings:
        name = "payments"
        indexes = [
            # Invoice lookup: find all payments for an invoice
            [("_org.org_id", 1), ("invoice_ref", 1)],
            # Gateway tier filtering: platform-tier settlement queries
            [("_org.org_id", 1), ("gateway_tier", 1), ("status", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, payment_number: str
    ) -> Optional["PaymentDoc"]:
        """Find a payment by its unique number."""
        return await cls.org_find_one(ctx, {"payment_number": payment_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str
    ) -> List["PaymentDoc"]:
        """Find all payments linked to an invoice."""
        return await cls.org_find(
            ctx,
            {"invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
            limit=100,
        )

    @classmethod
    async def find_platform_unsettled(
        cls,
        ctx: OrgContext,
        period_start: str,
        period_end: str,
    ) -> List["PaymentDoc"]:
        """
        Find platform-tier payments in a period that haven't been settled.

        Used by settlement generation to aggregate commission.
        """
        return await cls.org_find(
            ctx,
            {
                "gateway_tier": GatewayTier.PLATFORM,
                "status": PaymentStatus.CAPTURED,
                "payment_date": {
                    "$gte": period_start,
                    "$lte": period_end,
                },
            },
            sort=[("payment_date", 1)],
            limit=10000,
        )

    @property
    def is_platform_payment(self) -> bool:
        """Whether this payment went through the platform's gateway."""
        return self.gateway_tier == GatewayTier.PLATFORM
