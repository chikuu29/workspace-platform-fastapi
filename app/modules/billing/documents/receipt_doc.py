"""
ReceiptDoc — Beanie document for the receipts collection.

Auto-generated when an invoice is fully paid. Provides a read-only
proof of payment with a snapshot of invoice + payment data at the
time of receipt generation.

Receipts CANNOT be manually created or edited after generation.
Only ReceiptService._generate_receipt() creates them (internal).

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_RECEIPT,
    ReceiptStatus,
)
from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)


class ReceiptData(BaseModel):
    """Business fields for Receipt stored nested under 'data'."""
    receipt_number: str = ""
    invoice_ref: str = ""
    order_ref: str = ""
    payment_refs: List[str] = Field(default_factory=list)
    customer_ref: Optional[CustomerRefEmbed] = None
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    amount_paid: float = 0.0
    currency: str = DEFAULT_CURRENCY
    payment_method: str = ""
    payment_date: str = ""
    status: str = ReceiptStatus.ISSUED
    source_app: str = ""


class ReceiptDoc(BillingDocument):
    """
    Receipt Beanie document — stored in the receipts collection.

    Auto-generated when an invoice is fully paid. Acts as a read-only
    proof of payment — cannot be edited after creation.
    """

    data: ReceiptData = Field(default_factory=ReceiptData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def receipt_number(self) -> str:
        return self.data.receipt_number

    @receipt_number.setter
    def receipt_number(self, value: str) -> None:
        self.data.receipt_number = value

    @property
    def invoice_ref(self) -> str:
        return self.data.invoice_ref

    @invoice_ref.setter
    def invoice_ref(self, value: str) -> None:
        self.data.invoice_ref = value

    @property
    def order_ref(self) -> str:
        return self.data.order_ref

    @order_ref.setter
    def order_ref(self, value: str) -> None:
        self.data.order_ref = value

    @property
    def payment_refs(self) -> List[str]:
        return self.data.payment_refs

    @payment_refs.setter
    def payment_refs(self, value: List[str]) -> None:
        self.data.payment_refs = value

    @property
    def customer_ref(self) -> Optional[CustomerRefEmbed]:
        return self.data.customer_ref

    @customer_ref.setter
    def customer_ref(self, value: Optional[CustomerRefEmbed]) -> None:
        self.data.customer_ref = value

    @property
    def subtotal(self) -> float:
        return self.data.subtotal

    @subtotal.setter
    def subtotal(self, value: float) -> None:
        self.data.subtotal = value

    @property
    def tax_amount(self) -> float:
        return self.data.tax_amount

    @tax_amount.setter
    def tax_amount(self, value: float) -> None:
        self.data.tax_amount = value

    @property
    def total(self) -> float:
        return self.data.total

    @total.setter
    def total(self, value: float) -> None:
        self.data.total = value

    @property
    def amount_paid(self) -> float:
        return self.data.amount_paid

    @amount_paid.setter
    def amount_paid(self, value: float) -> None:
        self.data.amount_paid = value

    @property
    def currency(self) -> str:
        return self.data.currency

    @currency.setter
    def currency(self, value: str) -> None:
        self.data.currency = value

    @property
    def payment_method(self) -> str:
        return self.data.payment_method

    @payment_method.setter
    def payment_method(self, value: str) -> None:
        self.data.payment_method = value

    @property
    def payment_date(self) -> str:
        return self.data.payment_date

    @payment_date.setter
    def payment_date(self, value: str) -> None:
        self.data.payment_date = value

    @property
    def status(self) -> str:
        return self.data.status

    @status.setter
    def status(self, value: str) -> None:
        self.data.status = value

    @property
    def source_app(self) -> str:
        return self.data.source_app

    @source_app.setter
    def source_app(self, value: str) -> None:
        self.data.source_app = value

    class Settings:
        name = "receipts"
        indexes = [
            # Unique number lookup
            [("_org.org_id", 1), ("data.receipt_number", 1)],
            # Invoice lookup: find receipt for an invoice
            [("_org.org_id", 1), ("data.invoice_ref", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, receipt_number: str,
    ) -> Optional["ReceiptDoc"]:
        """Find a receipt by its unique number."""
        return await cls.org_find_one(ctx, {"data.receipt_number": receipt_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> Optional["ReceiptDoc"]:
        """Find the receipt for a specific invoice."""
        return await cls.org_find_one(ctx, {"data.invoice_ref": invoice_ref})
