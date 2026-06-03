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
from pydantic import Field

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


class ReceiptDoc(BillingDocument):
    """
    Receipt Beanie document — stored in the receipts collection.

    Auto-generated when an invoice is fully paid. Acts as a read-only
    proof of payment — cannot be edited after creation.

    Links to the source invoice and all payments that contributed
    to the full payment.

    Usage:
        receipt = await ReceiptDoc.find_by_invoice(ctx, "INV/2026-27/0001")
        receipt = await ReceiptDoc.find_by_number(ctx, "RCT/2026-27/0001")
    """

    # Identity
    receipt_number: Indexed(str, unique=True) = ""

    # Linked documents
    invoice_ref: str = ""
    order_ref: str = ""
    payment_refs: List[str] = Field(default_factory=list)

    # Customer (snapshot from invoice at time of receipt generation)
    customer_ref: Optional[CustomerRefEmbed] = None

    # Financials (snapshot from invoice at time of receipt generation)
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    amount_paid: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Payment summary
    payment_method: str = ""     # Primary method used for final payment
    payment_date: str = ""       # Date of final payment

    # Status
    status: str = ReceiptStatus.ISSUED

    # Source tracking
    source_app: str = ""

    class Settings:
        name = "receipts"
        indexes = [
            # Invoice lookup: find receipt for an invoice
            [("_org.org_id", 1), ("invoice_ref", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, receipt_number: str,
    ) -> Optional["ReceiptDoc"]:
        """Find a receipt by its unique number."""
        return await cls.org_find_one(ctx, {"receipt_number": receipt_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> Optional["ReceiptDoc"]:
        """Find the receipt for a specific invoice."""
        return await cls.org_find_one(ctx, {"invoice_ref": invoice_ref})
