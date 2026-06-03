"""
Credit Note Schemas — Pydantic request/response contracts for credit notes.

Used by domain apps to issue credit notes (refunds) via the BillingService SDK.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.modules.billing.schemas.common import AuditInfoResponse


class CreditNoteLineItem(BaseModel):
    """A line item being credited/refunded."""

    description: str
    quantity: float = Field(1.0, gt=0)
    unit_price: float = Field(0.0, ge=0)
    tax_category: str = "higher"
    source_item_code: str = ""


class IssueCreditNoteInput(BaseModel):
    """
    Input for issuing a credit note against an invoice.

    Usage:
        cn_input = IssueCreditNoteInput(
            invoice_ref="INV/2026-27/0001",
            reason="Partial refund — membership downgrade",
            refund_amount=2000.0,
        )
        cn = await billing.credit_notes.issue(cn_input)
    """

    invoice_ref: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=1000)
    refund_amount: float = Field(..., gt=0, le=10_000_000)
    line_items: List[CreditNoteLineItem] = Field(default_factory=list)
    notes: str = Field("", max_length=2000)


class CreditNoteResponse(BaseModel):
    """Serialized credit note response for API consumers."""

    credit_note_number: str
    invoice_ref: str
    reason: str
    line_items: List[Dict[str, Any]]
    subtotal: float
    tax_amount: float
    total: float
    currency: str
    status: str
    issue_date: str
    notes: str
    source_app: str
    audit: AuditInfoResponse


def map_credit_note_doc_to_response(doc: Any) -> CreditNoteResponse:
    """Map a CreditNoteDoc to CreditNoteResponse for API serialization."""
    return CreditNoteResponse(
        credit_note_number=doc.credit_note_number,
        invoice_ref=doc.invoice_ref,
        reason=doc.reason,
        line_items=doc.line_items if isinstance(doc.line_items, list) else [],
        subtotal=doc.subtotal,
        tax_amount=doc.tax_amount,
        total=doc.total,
        currency=getattr(doc, "currency", "INR"),
        status=doc.status,
        issue_date=getattr(doc, "issue_date", ""),
        notes=getattr(doc, "notes", ""),
        source_app=getattr(doc, "source_app", ""),
        audit=AuditInfoResponse(
            created_by=doc.meta.created.by if doc.meta else "",
            created_at=doc.meta.created.at.isoformat() if doc.meta and doc.meta.created else "",
            updated_at=doc.meta.updated.at.isoformat() if doc.meta and doc.meta.updated else "",
        ),
    )
