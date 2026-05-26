"""Payment routes — record payments, list, and get details."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import created, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.db.database import get_database
from app.modules.billing_management.services.payment_service import PaymentService

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
) -> PaymentService:
    return PaymentService(db, ctx)


@router.post("")
async def record_payment(
    request: Request,
    service: PaymentService = Depends(_get_service),
):
    """
    Record a payment against an invoice.

    Supports all manual methods: cash, upi, card, bank_transfer, etc.
    Automatically updates the invoice status.
    """
    data = await request.json()
    document = await service.record_payment(data)
    return created(message="Payment recorded successfully.", data=document)


@router.get("")
async def list_payments(
    invoice_ref: str = Query(None, description="Filter by invoice number"),
    method: str = Query(None, description="Filter by method: cash, upi, card, etc."),
    status: str = Query(None, description="Filter by status: pending, captured, failed"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: PaymentService = Depends(_get_service),
):
    """List payments with optional filters."""
    documents, total = await service.list_payments(
        invoice_ref=invoice_ref,
        method=method,
        status=status,
        skip=skip,
        limit=limit,
    )
    return paginated(message="Payments retrieved.", data=documents, total=total, skip=skip, limit=limit)


@router.get("/{payment_number:path}")
async def get_payment(
    payment_number: str,
    service: PaymentService = Depends(_get_service),
):
    """Get a single payment by number."""
    document = await service.get_payment(payment_number)
    return ok(message="Payment retrieved.", data=document)
