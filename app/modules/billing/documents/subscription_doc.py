"""
SubscriptionDoc — Beanie document for the subscriptions collection.

Tracks recurring subscriptions linking a customer to a catalog plan.
Auto-generates invoices on renewal if auto_renew is True.

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    BillingCycle,
    DEFAULT_CURRENCY,
    ENTITY_SUBSCRIPTION,
    SubscriptionStatus,
)
from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)


class SubscriptionDoc(BillingDocument):
    """
    Subscription Beanie document — stored in the subscriptions collection.

    Links a customer to a plan with billing cycle tracking.
    Auto-generates invoices on renewal when auto_renew is True.

    Usage:
        doc = SubscriptionDoc.create_for_org(ctx, entity_type=ENTITY_SUBSCRIPTION, ...)
        await doc.insert()

        due = await SubscriptionDoc.find_due_for_renewal(ctx, "2026-06-01")
    """

    # Identity
    subscription_number: Indexed(str, unique=True) = ""

    # Customer (resolved by the calling app module)
    customer_ref: Optional[CustomerRefEmbed] = None

    # Plan details
    plan_code: str = ""
    plan_name: str = ""
    billing_cycle: str = BillingCycle.MONTHLY
    unit_price: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Status & dates
    status: str = SubscriptionStatus.ACTIVE
    current_period_start: str = ""
    current_period_end: str = ""
    next_billing_date: str = ""
    auto_renew: bool = True
    renewal_count: int = 0

    # Source tracking — which app generated this subscription
    source_app: str = ""

    # Notes
    notes: str = ""

    class Settings:
        name = "subscriptions"
        indexes = [
            # Renewal processing: org + active + next billing date
            [("_org.org_id", 1), ("status", 1), ("next_billing_date", 1)],
            # Customer history: org + customer ref_id
            [("_org.org_id", 1), ("customer_ref.ref_id", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, sub_number: str
    ) -> Optional["SubscriptionDoc"]:
        """Find a subscription by its unique number."""
        return await cls.org_find_one(ctx, {"subscription_number": sub_number})

    @classmethod
    async def find_due_for_renewal(
        cls, ctx: OrgContext, as_of_date: str
    ) -> List["SubscriptionDoc"]:
        """Find active auto-renew subscriptions due for billing."""
        return await cls.org_find(
            ctx,
            {
                "status": SubscriptionStatus.ACTIVE,
                "auto_renew": True,
                "next_billing_date": {"$lte": as_of_date},
            },
            sort=[("next_billing_date", 1)],
            limit=500,
        )
