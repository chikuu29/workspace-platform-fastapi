"""
SettlementDoc — Beanie document for the settlements collection.

Aggregates platform-tier payments for a period, computes total
commission, and tracks the payout to the org owner.

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_SETTLEMENT,
    SettlementMode,
    SettlementStatus,
)
from app.modules.billing.documents.base import BillingDocument


class SettlementDoc(BillingDocument):
    """
    Settlement Beanie document — stored in the settlements collection.

    Each settlement aggregates platform-tier payments for a billing
    period, computes total commission, and tracks payout to the owner.

    Usage:
        doc = SettlementDoc.create_for_org(ctx, entity_type=ENTITY_SETTLEMENT, ...)
        await doc.insert()

        pending = await SettlementDoc.find_pending(ctx)
    """

    # Identity
    settlement_number: Indexed(str, unique=True) = ""

    # Period covered by this settlement
    period_start: str = ""           # ISO date
    period_end: str = ""

    # Money breakdown
    total_collected: float = 0.0     # Total payments via platform gateway
    total_commission: float = 0.0    # Platform's cut
    total_refunds: float = 0.0       # Refunds during period
    total_adjustments: float = 0.0   # Manual adjustments
    net_payable: float = 0.0         # What owner receives
    currency: str = DEFAULT_CURRENCY

    # Settlement execution
    status: str = SettlementStatus.PENDING
    mode: str = SettlementMode.MANUAL    # manual | automatic
    paid_via: str = ""                   # bank_transfer, upi, etc.
    paid_at: str = ""                    # ISO datetime
    reference_id: str = ""               # Bank txn reference

    # Linked payments (payment_numbers from PaymentDoc)
    payment_refs: List[str] = Field(default_factory=list)
    payment_count: int = 0

    # Notes
    notes: str = ""

    class Settings:
        name = "settlements"
        indexes = [
            # Status lookup for pending payouts
            [("_org.org_id", 1), ("status", 1)],
            # Period lookup
            [("_org.org_id", 1), ("period_end", -1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, stl_number: str
    ) -> Optional["SettlementDoc"]:
        """Find a settlement by its unique number."""
        return await cls.org_find_one(ctx, {"settlement_number": stl_number})

    @classmethod
    async def find_pending(
        cls, ctx: OrgContext
    ) -> List["SettlementDoc"]:
        """Find settlements pending payout."""
        return await cls.org_find(
            ctx,
            {"status": SettlementStatus.PENDING},
            sort=[("period_end", -1)],
        )
