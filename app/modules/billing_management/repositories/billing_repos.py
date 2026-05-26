"""Collection-specific billing repositories — thin wrappers around BillingRepository."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.context import OrgContext
from app.modules.billing_management.constants import (
    COLL_CREDIT_NOTES,
    COLL_GATEWAY_CONFIGS,
    COLL_INVOICES,
    COLL_PAYMENTS,
    COLL_REMINDERS,
    COLL_SETTLEMENTS,
    COLL_SUBSCRIPTIONS,
    COLL_TAX_PROFILES,
    ENTITY_CREDIT_NOTE,
    ENTITY_GATEWAY_CONFIG,
    ENTITY_INVOICE,
    ENTITY_PAYMENT,
    ENTITY_REMINDER,
    ENTITY_SETTLEMENT,
    ENTITY_SUBSCRIPTION,
    ENTITY_TAX_PROFILE,
    GatewayTier,
    PaymentStatus,
)
from app.modules.billing_management.repositories.billing_repository import (
    BillingRepository,
)


class InvoiceRepository(BillingRepository):
    """Repository for the billing_invoices collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_INVOICES, ctx)

    async def find_by_number(self, invoice_number: str) -> Optional[Dict[str, Any]]:
        """Find an invoice by its unique number."""
        return await self.find_one({"data.invoice_number": invoice_number})

    async def find_by_customer(
        self,
        ref_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find invoices for a specific customer."""
        return await self.find(
            {"data.customer_ref.ref_id": ref_id},
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    async def find_overdue(
        self,
        as_of_date: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find invoices that are past due date and not fully paid."""
        return await self.find(
            {
                "data.status": {"$in": ["sent", "partial"]},
                "data.due_date": {"$lt": as_of_date},
            },
            sort=[("data.due_date", 1)],
            skip=skip,
            limit=limit,
        )


class PaymentRepository(BillingRepository):
    """Repository for the billing_payments collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_PAYMENTS, ctx)

    async def find_by_number(self, payment_number: str) -> Optional[Dict[str, Any]]:
        """Find a payment by its unique number."""
        return await self.find_one({"data.payment_number": payment_number})

    async def find_by_invoice(self, invoice_ref: str) -> List[Dict[str, Any]]:
        """Find all payments linked to an invoice."""
        return await self.find(
            {"data.invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
            limit=100,
        )

    async def find_platform_unsettled(
        self,
        period_start: str,
        period_end: str,
    ) -> List[Dict[str, Any]]:
        """
        Find platform-tier payments in a period that haven't been settled.

        Used by settlement generation to aggregate commission.
        """
        return await self.find(
            {
                "data.gateway_tier": GatewayTier.PLATFORM,
                "data.status": PaymentStatus.CAPTURED,
                "data.payment_date": {
                    "$gte": period_start,
                    "$lte": period_end,
                },
            },
            sort=[("data.payment_date", 1)],
            limit=10000,
        )


class SubscriptionRepository(BillingRepository):
    """Repository for the billing_subscriptions collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_SUBSCRIPTIONS, ctx)

    async def find_by_number(self, sub_number: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"data.subscription_number": sub_number})

    async def find_due_for_renewal(self, as_of_date: str) -> List[Dict[str, Any]]:
        """Find active auto-renew subscriptions due for billing."""
        return await self.find(
            {
                "data.status": "active",
                "data.auto_renew": True,
                "data.next_billing_date": {"$lte": as_of_date},
            },
            sort=[("data.next_billing_date", 1)],
            limit=500,
        )


class CreditNoteRepository(BillingRepository):
    """Repository for the billing_credit_notes collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_CREDIT_NOTES, ctx)

    async def find_by_number(self, cn_number: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"data.credit_note_number": cn_number})

    async def find_by_invoice(self, invoice_ref: str) -> List[Dict[str, Any]]:
        return await self.find(
            {"data.invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
        )


class TaxProfileRepository(BillingRepository):
    """Repository for the billing_tax_profiles collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_TAX_PROFILES, ctx)

    async def find_default(self) -> Optional[Dict[str, Any]]:
        """Find the default tax profile for the org."""
        return await self.find_one({"data.is_default": True})

    async def find_by_gstin(self, gstin: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"data.gstin": gstin})


class ReminderRepository(BillingRepository):
    """Repository for the billing_reminders collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_REMINDERS, ctx)

    async def find_due(self, as_of_date: str) -> List[Dict[str, Any]]:
        """Find scheduled reminders that are due for processing."""
        return await self.find(
            {
                "data.status": "scheduled",
                "data.scheduled_date": {"$lte": as_of_date},
            },
            sort=[("data.scheduled_date", 1)],
            limit=500,
        )


class GatewayConfigRepository(BillingRepository):
    """Repository for the billing_gateway_configs collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_GATEWAY_CONFIGS, ctx)

    async def find_active_config(self) -> Optional[Dict[str, Any]]:
        """
        Find the active gateway config for the current org + app.

        There should be at most one active config per (org_id, app_code).
        The unique index enforces this.
        """
        return await self.find_one({
            "_org.app_code": self._ctx.app_code,
            "data.is_active": True,
        })


class SettlementRepository(BillingRepository):
    """Repository for the billing_settlements collection."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        super().__init__(db, COLL_SETTLEMENTS, ctx)

    async def find_by_number(self, stl_number: str) -> Optional[Dict[str, Any]]:
        return await self.find_one({"data.settlement_number": stl_number})

    async def find_pending(self) -> List[Dict[str, Any]]:
        """Find settlements pending payout."""
        return await self.find(
            {"data.status": "pending"},
            sort=[("data.period_end", -1)],
        )
