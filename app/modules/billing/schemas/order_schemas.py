"""
Order Schemas — Pydantic request/response contracts for billing orders.

Used by domain apps to create orders via the BillingService SDK.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.modules.billing.schemas.common import (
    AuditInfoResponse,
    CustomerRefSchema,
)
from app.modules.billing.schemas.line_items import LineItemInput


class CreateOrderInput(BaseModel):
    """
    Input for creating a billing order.

    The domain app provides pre-validated line items, customer info,
    and tax context. Billing computes totals + tax.

    Usage:
        order_input = CreateOrderInput(
            customer_ref=CustomerRefSchema(...),
            line_items=[ServiceLineItem(...)],
            seller_gstin="29AABCU9603R1ZM",
            source_ref={"app": "myGym", "ref_type": "subscription", "ref_id": "SUB-001"},
        )
        order = await billing.orders.create(order_input)
    """

    customer_ref: CustomerRefSchema
    line_items: List[LineItemInput] = Field(..., min_length=1)

    # Tax context
    seller_gstin: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""

    # Currency
    currency: str = "INR"

    # Source app reference — links to the domain app's entity
    source_ref: Optional[Dict[str, str]] = None

    # Notes
    notes: str = ""


class OrderResponse(BaseModel):
    """Serialized order response for API consumers."""

    order_number: str
    customer_ref: Optional[Dict[str, Any]] = None
    source_ref: Optional[Dict[str, Any]] = None
    line_items: List[Dict[str, Any]]
    subtotal: float
    tax_amount: float
    total: float
    currency: str
    status: str
    invoice_ref: str
    receipt_ref: str
    source_app: str
    notes: str
    audit: AuditInfoResponse


def map_order_doc_to_response(doc: Any) -> OrderResponse:
    """Map an OrderDoc to OrderResponse for API serialization."""
    return OrderResponse(
        order_number=doc.order_number,
        customer_ref=doc.customer_ref.model_dump() if doc.customer_ref else None,
        source_ref=doc.source_ref.model_dump() if doc.source_ref else None,
        line_items=[li.model_dump() for li in doc.line_items],
        subtotal=doc.subtotal,
        tax_amount=doc.tax_amount,
        total=doc.total,
        currency=doc.currency,
        status=doc.status,
        invoice_ref=doc.invoice_ref,
        receipt_ref=doc.receipt_ref,
        source_app=doc.source_app,
        notes=doc.notes,
        audit=AuditInfoResponse(
            created_by=doc.meta.created.by if doc.meta else "",
            created_at=doc.meta.created.at.isoformat() if doc.meta and doc.meta.created else "",
            updated_at=doc.meta.updated.at.isoformat() if doc.meta and doc.meta.updated else "",
        ),
    )
