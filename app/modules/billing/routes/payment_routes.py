"""Payment routes — record payments, list, and get details."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.common.responses import created, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.db.database import get_database
from app.modules.billing.services.payment_service import PaymentService
from app.modules.billing.schemas.common import SuccessEnvelope, PaginatedEnvelope
from app.modules.billing.schemas.payment_schemas import (
    RecordPaymentInput,
    PaymentResponse,
    map_payment_doc_to_response,
)

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
) -> PaymentService:
    return PaymentService(db, ctx)


@router.post("", response_model=SuccessEnvelope[PaymentResponse], status_code=201)
async def record_payment(
    input_data: RecordPaymentInput,
    service: PaymentService = Depends(_get_service),
):
    """
    Record a payment against an invoice.

    Supports all manual methods: cash, upi, card, bank_transfer, etc.
    Automatically updates the invoice status.
    """
    doc = await service.record(input_data)
    mapped = map_payment_doc_to_response(doc)
    return created(message="Payment recorded successfully.", data=mapped)


@router.get("", response_model=PaginatedEnvelope[PaymentResponse])
async def list_payments(
    invoice_ref: str = Query(None, description="Filter by invoice number"),
    method: str = Query(None, description="Filter by method: cash, upi, card, etc."),
    status: str = Query(None, description="Filter by status: pending, captured, failed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: PaymentService = Depends(_get_service),
):
    """List payments with optional filters."""
    documents, total = await service.list(
        invoice_ref=invoice_ref,
        method=method,
        status=status,
        skip=skip,
        limit=limit,
    )
    mapped = [map_payment_doc_to_response(doc) for doc in documents]
    return paginated(message="Payments retrieved.", data=mapped, total=total, skip=skip, limit=limit)


@router.get("/{payment_number:path}", response_model=SuccessEnvelope[PaymentResponse])
async def get_payment(
    payment_number: str,
    service: PaymentService = Depends(_get_service),
):
    """Get a single payment by number."""
    doc = await service.get(payment_number)
    mapped = map_payment_doc_to_response(doc)
    return ok(message="Payment retrieved.", data=mapped)
