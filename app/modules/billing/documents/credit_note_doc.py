"""
CreditNoteDoc — Beanie document for the credit_notes collection.

Represents a refund or credit adjustment against an invoice.
Lifecycle: draft → issued → applied → (void)

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from beanie import Indexed
from pydantic import Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    CreditNoteStatus,
    DEFAULT_CURRENCY,
    ENTITY_CREDIT_NOTE,
)
from app.modules.billing.documents.base import BillingDocument


class CreditNoteDoc(BillingDocument):
    """
    Credit note Beanie document — stored in the credit_notes collection.

    Linked to an invoice via invoice_ref. Tracks refund reason,
    adjusted line items, and tax recalculations.

    Usage:
        doc = CreditNoteDoc.create_for_org(ctx, entity_type=ENTITY_CREDIT_NOTE, ...)
        await doc.insert()

        cn = await CreditNoteDoc.find_by_number(ctx, "CN/2026-27/0001")
    """

    # Identity
    credit_note_number: Indexed(str, unique=True) = ""

    # Invoice linkage — original invoice this credit note is against
    invoice_ref: str = ""

    # Reason for credit
    reason: str = ""

    # Adjusted line items (stored as dicts for flexibility)
    line_items: List[Dict[str, Any]] = Field(default_factory=list)

    # Financials
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Status
    status: str = CreditNoteStatus.DRAFT

    class Settings:
        name = "credit_notes"
        indexes = [
            # Invoice lookup: find all credit notes for an invoice
            [("_org.org_id", 1), ("invoice_ref", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, cn_number: str
    ) -> Optional["CreditNoteDoc"]:
        """Find a credit note by its unique number."""
        return await cls.org_find_one(ctx, {"credit_note_number": cn_number})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str
    ) -> List["CreditNoteDoc"]:
        """Find all credit notes linked to an invoice."""
        return await cls.org_find(
            ctx,
            {"invoice_ref": invoice_ref},
            sort=[("_meta.created.at", -1)],
        )
