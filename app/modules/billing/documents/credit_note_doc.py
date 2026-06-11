"""
CreditNoteDoc — Beanie document for the credit_notes collection.

Represents a refund or credit adjustment against an invoice.
Lifecycle: draft → issued → applied → (void)

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from beanie import Indexed
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    CreditNoteStatus,
    DEFAULT_CURRENCY,
    ENTITY_CREDIT_NOTE,
)
from app.modules.billing.documents.base import BillingDocument


class CreditNoteData(BaseModel):
    """Business fields for CreditNote stored nested under 'data'."""
    credit_note_number: str = ""
    invoice_ref: str = ""
    reason: str = ""
    line_items: List[Dict[str, Any]] = Field(default_factory=list)
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = DEFAULT_CURRENCY
    status: str = CreditNoteStatus.DRAFT


class CreditNoteDoc(BillingDocument):
    """
    Credit note Beanie document — stored in the credit_notes collection.

    Linked to an invoice via invoice_ref. Tracks refund reason,
    adjusted line items, and tax recalculations.
    """

    data: CreditNoteData = Field(default_factory=CreditNoteData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def credit_note_number(self) -> str:
        return self.data.credit_note_number

    @credit_note_number.setter
    def credit_note_number(self, value: str) -> None:
        self.data.credit_note_number = value

    @property
    def invoice_ref(self) -> str:
        return self.data.invoice_ref

    @invoice_ref.setter
    def invoice_ref(self, value: str) -> None:
        self.data.invoice_ref = value

    @property
    def reason(self) -> str:
        return self.data.reason

    @reason.setter
    def reason(self, value: str) -> None:
        self.data.reason = value

    @property
    def line_items(self) -> List[Dict[str, Any]]:
        return self.data.line_items

    @line_items.setter
    def line_items(self, value: List[Dict[str, Any]]) -> None:
        self.data.line_items = value

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
    def currency(self) -> str:
        return self.data.currency

    @currency.setter
    def currency(self, value: str) -> None:
        self.data.currency = value

    @property
    def status(self) -> str:
        return self.data.status

    @status.setter
    def status(self, value: str) -> None:
        self.data.status = value

    class Settings:
        name = "credit_notes"
        indexes = [
            # Unique number lookup
            [("_org.org_id", 1), ("data.credit_note_number", 1)],
            # Invoice lookup: find all credit notes for an invoice
            [("_org.org_id", 1), ("data.invoice_ref", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, cn_number: str
    ) -> Optional["CreditNoteDoc"]:
        """Find a credit note by its unique number."""
        return await cls.org_find_one(ctx, {"data.credit_note_number": cn_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str
    ) -> List["CreditNoteDoc"]:
        """Find all credit notes linked to an invoice."""
        return await cls.org_find(
            ctx,
            {"data.invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
        )
