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
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_PAYMENT,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.billing.documents.base import BillingDocument


class PaymentData(BaseModel):
    """Business fields for Payment stored nested under 'data'."""
    payment_number: str = ""
    invoice_ref: str = ""
    amount: float = 0.0
    currency: str = DEFAULT_CURRENCY
    method: str = PaymentMethod.CASH
    gateway_tier: str = ""
    gateway_provider: str = ""
    gateway_payment_id: str = ""
    gateway_order_id: str = ""
    gateway_signature: str = ""
    commission_rate: float = 0.0
    commission_amount: float = 0.0
    net_to_owner: float = 0.0
    status: str = PaymentStatus.CAPTURED
    payment_date: str = ""
    transaction_ref: str = ""
    notes: str = ""
    source_app: str = ""


class PaymentDoc(BillingDocument):
    """
    Payment Beanie document — stored in payments collection.

    Linked to an invoice via invoice_ref. Commission fields are
    reserved for future platform-tier gateway payments.
    """

    data: PaymentData = Field(default_factory=PaymentData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def payment_number(self) -> str:
        return self.data.payment_number

    @payment_number.setter
    def payment_number(self, value: str) -> None:
        self.data.payment_number = value

    @property
    def invoice_ref(self) -> str:
        return self.data.invoice_ref

    @invoice_ref.setter
    def invoice_ref(self, value: str) -> None:
        self.data.invoice_ref = value

    @property
    def amount(self) -> float:
        return self.data.amount

    @amount.setter
    def amount(self, value: float) -> None:
        self.data.amount = value

    @property
    def currency(self) -> str:
        return self.data.currency

    @currency.setter
    def currency(self, value: str) -> None:
        self.data.currency = value

    @property
    def method(self) -> str:
        return self.data.method

    @method.setter
    def method(self, value: str) -> None:
        self.data.method = value

    @property
    def gateway_tier(self) -> str:
        return self.data.gateway_tier

    @gateway_tier.setter
    def gateway_tier(self, value: str) -> None:
        self.data.gateway_tier = value

    @property
    def gateway_provider(self) -> str:
        return self.data.gateway_provider

    @gateway_provider.setter
    def gateway_provider(self, value: str) -> None:
        self.data.gateway_provider = value

    @property
    def gateway_payment_id(self) -> str:
        return self.data.gateway_payment_id

    @gateway_payment_id.setter
    def gateway_payment_id(self, value: str) -> None:
        self.data.gateway_payment_id = value

    @property
    def gateway_order_id(self) -> str:
        return self.data.gateway_order_id

    @gateway_order_id.setter
    def gateway_order_id(self, value: str) -> None:
        self.data.gateway_order_id = value

    @property
    def gateway_signature(self) -> str:
        return self.data.gateway_signature

    @gateway_signature.setter
    def gateway_signature(self, value: str) -> None:
        self.data.gateway_signature = value

    @property
    def commission_rate(self) -> float:
        return self.data.commission_rate

    @commission_rate.setter
    def commission_rate(self, value: float) -> None:
        self.data.commission_rate = value

    @property
    def commission_amount(self) -> float:
        return self.data.commission_amount

    @commission_amount.setter
    def commission_amount(self, value: float) -> None:
        self.data.commission_amount = value

    @property
    def net_to_owner(self) -> float:
        return self.data.net_to_owner

    @net_to_owner.setter
    def net_to_owner(self, value: float) -> None:
        self.data.net_to_owner = value

    @property
    def status(self) -> str:
        return self.data.status

    @status.setter
    def status(self, value: str) -> None:
        self.data.status = value

    @property
    def payment_date(self) -> str:
        return self.data.payment_date

    @payment_date.setter
    def payment_date(self, value: str) -> None:
        self.data.payment_date = value

    @property
    def transaction_ref(self) -> str:
        return self.data.transaction_ref

    @transaction_ref.setter
    def transaction_ref(self, value: str) -> None:
        self.data.transaction_ref = value

    @property
    def notes(self) -> str:
        return self.data.notes

    @notes.setter
    def notes(self, value: str) -> None:
        self.data.notes = value

    @property
    def source_app(self) -> str:
        return self.data.source_app

    @source_app.setter
    def source_app(self, value: str) -> None:
        self.data.source_app = value

    class Settings:
        name = "payments"
        indexes = [
            # Unique payment number lookup
            [("_org.org_id", 1), ("data.payment_number", 1)],
            # Invoice lookup: find all payments for an invoice
            [("_org.org_id", 1), ("data.invoice_ref", 1)],
            # Status filtering
            [("_org.org_id", 1), ("data.status", 1), ("_meta.created.at", -1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, payment_number: str,
    ) -> Optional["PaymentDoc"]:
        """Find a payment by its unique number."""
        return await cls.org_find_one(ctx, {"data.payment_number": payment_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> List["PaymentDoc"]:
        """Find all payments linked to an invoice."""
        return await cls.org_find(
            ctx,
            {"data.invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
            limit=100,
        )
