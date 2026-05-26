"""Invoice routes — create, list, update, send, void invoices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import created, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.db.database import get_database
from app.modules.billing_management.services.invoice_service import InvoiceService

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
) -> InvoiceService:
    return InvoiceService(db, ctx)


@router.post("")
async def create_invoice(
    request: Request,
    service: InvoiceService = Depends(_get_service),
):
    """
    Create an invoice with automatic GST computation.

    Pass seller_gstin and buyer_gstin in the request body.
    Line items are priced and taxed automatically.
    """
    data = await request.json()
    document = await service.create_invoice(data)
    return created(message="Invoice created successfully.", data=document)


@router.get("")
async def list_invoices(
    status: str = Query(None, description="Filter by status: draft, sent, paid, partial, overdue, void"),
    customer_ref_id: str = Query(None, description="Filter by customer ref_id"),
    source_app: str = Query(None, description="Filter by source app code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: InvoiceService = Depends(_get_service),
):
    """List invoices with optional filters."""
    documents, total = await service.list_invoices(
        status=status,
        customer_ref_id=customer_ref_id,
        source_app=source_app,
        skip=skip,
        limit=limit,
    )
    return paginated(message="Invoices retrieved.", data=documents, total=total, skip=skip, limit=limit)


@router.get("/{invoice_number:path}")
async def get_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Get a single invoice with payment history."""
    document = await service.get_invoice(invoice_number)
    return ok(message="Invoice retrieved.", data=document)


@router.put("/{invoice_number:path}")
async def update_invoice(
    invoice_number: str,
    request: Request,
    service: InvoiceService = Depends(_get_service),
):
    """Update a draft invoice."""
    data = await request.json()
    document = await service.update_invoice(invoice_number, data)
    return ok(message="Invoice updated successfully.", data=document)


@router.post("/{invoice_number:path}/send")
async def send_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Mark a draft invoice as sent."""
    document = await service.send_invoice(invoice_number)
    return ok(message="Invoice marked as sent.", data=document)


@router.post("/{invoice_number:path}/void")
async def void_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Void/cancel an invoice."""
    document = await service.void_invoice(invoice_number)
    return ok(message="Invoice voided.", data=document)
