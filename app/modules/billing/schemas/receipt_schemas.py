"""
Receipt Schemas — Pydantic response contracts for receipts.

Receipts are read-only (auto-generated) — no input schema needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.modules.billing.schemas.common import AuditInfoResponse


class ReceiptResponse(BaseModel):
    """Serialized receipt response for API consumers."""

    receipt_number: str
    invoice_ref: str
    order_ref: str
    payment_refs: List[str]
    customer_ref: Optional[Dict[str, Any]] = None
    subtotal: float
    tax_amount: float
    total: float
    amount_paid: float
    currency: str
    payment_method: str
    payment_date: str
    status: str
    source_app: str
    audit: AuditInfoResponse


def map_receipt_doc_to_response(doc: Any) -> ReceiptResponse:
    """Map a ReceiptDoc to ReceiptResponse for API serialization."""
    return ReceiptResponse(
        receipt_number=doc.receipt_number,
        invoice_ref=doc.invoice_ref,
        order_ref=doc.order_ref,
        payment_refs=doc.payment_refs,
        customer_ref=doc.customer_ref.model_dump() if doc.customer_ref else None,
        subtotal=doc.subtotal,
        tax_amount=doc.tax_amount,
        total=doc.total,
        amount_paid=doc.amount_paid,
        currency=doc.currency,
        payment_method=doc.payment_method,
        payment_date=doc.payment_date,
        status=doc.status,
        source_app=doc.source_app,
        audit=AuditInfoResponse(
            created_by=doc.meta.created.by if doc.meta else "",
            created_at=doc.meta.created.at.isoformat() if doc.meta and doc.meta.created else "",
            updated_at=doc.meta.updated.at.isoformat() if doc.meta and doc.meta.updated else "",
        ),
    )
