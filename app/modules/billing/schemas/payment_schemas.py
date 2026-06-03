"""
Payment request (internal contract) and response (API) schemas.

RecordPaymentInput is used by app modules to record payments against invoices.
PaymentResponse is the predictable shape returned to the frontend.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.modules.billing.documents.payment_doc import PaymentDoc

from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    PaymentMethod,
)
from app.modules.billing.schemas.common import AuditInfoResponse


# ── Internal Request (App Module → Billing Service) ──────────────────


class RecordPaymentInput(BaseModel):
    """
    Internal contract: app module records a payment via billing.

    The app has already validated the invoice exists and the customer
    is authorized to make the payment.

    Example usage:
        payment_input = RecordPaymentInput(
            invoice_ref="INV/2026-27/0001",
            amount=5000.0,
            method="upi",
            transaction_ref="UPI-TXN-123456",
        )
        payment_svc = PaymentService(db, ctx)
        result = await payment_svc.record_payment(payment_input)
    """

    invoice_ref: str = Field(
        ...,
        min_length=1,
        description="Invoice number to pay against",
    )
    amount: float = Field(
        ...,
        gt=0,
        le=10_000_000,
        description="Payment amount — capped at balance due server-side",
    )
    method: str = Field(
        PaymentMethod.CASH,
        description="Payment method: cash, upi, card, net_banking, bank_transfer, cheque",
    )
    currency: str = DEFAULT_CURRENCY
    payment_date: str = Field(
        "",
        description="ISO date (YYYY-MM-DD). Defaults to today if empty.",
    )
    transaction_ref: str = Field(
        "",
        max_length=200,
        description="External reference (UPI ref, bank transaction ID, cheque number)",
    )
    notes: str = Field("", max_length=2000)

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Ensure payment method is a valid enum value."""
        allowed = {e.value for e in PaymentMethod}
        if v not in allowed:
            msg = f"method must be one of: {', '.join(sorted(allowed))}"
            raise ValueError(msg)
        return v


# ── API Response (Billing → Frontend) ────────────────────────────────


class PaymentResponse(BaseModel):
    """
    Predictable payment response shape for frontend consumers.

    Includes gateway and commission fields (populated only for
    gateway-mediated payments in Phase 2).
    """

    # Identity
    payment_number: str
    invoice_ref: str

    # Amount
    amount: float
    currency: str

    # Method
    method: str
    status: str

    # Dates & references
    payment_date: str
    transaction_ref: str
    notes: str

    # Gateway (Phase 2 — empty for cash/manual payments)
    gateway_tier: str = ""
    gateway_provider: str = ""

    # Commission (Phase 2 — zero for non-platform payments)
    commission_rate: float = 0.0
    commission_amount: float = 0.0
    net_to_owner: float = 0.0

    # Audit trail
    audit: AuditInfoResponse


def map_payment_doc_to_response(doc: PaymentDoc) -> PaymentResponse:
    """Map a Beanie PaymentDoc to a PaymentResponse schema."""
    return PaymentResponse(
        payment_number=doc.payment_number,
        invoice_ref=doc.invoice_ref,
        amount=doc.amount,
        currency=doc.currency,
        method=doc.method,
        status=doc.status,
        payment_date=doc.payment_date,
        transaction_ref=doc.transaction_ref,
        notes=doc.notes or "",
        gateway_tier=doc.gateway_tier,
        gateway_provider=doc.gateway_provider,
        commission_rate=doc.commission_rate,
        commission_amount=doc.commission_amount,
        net_to_owner=doc.net_to_owner,
        audit=AuditInfoResponse(
            record_id=doc.meta_info.record_id,
            version=doc.meta_info.version,
            created_at=doc.meta_info.created.at,
            created_by=doc.meta_info.created.by,
            updated_at=doc.meta_info.updated.at if doc.meta_info.updated else None,
            updated_by=doc.meta_info.updated.by if doc.meta_info.updated else None,
        ),
    )
