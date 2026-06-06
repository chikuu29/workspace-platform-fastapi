"""Invoice routes — create, list, update, send, void invoices."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.common.responses import created, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.core.database import get_db
from app.modules.billing.services.invoice_service import InvoiceService
from app.modules.billing.schemas.common import SuccessEnvelope, PaginatedEnvelope
from app.modules.billing.schemas.invoice_schemas import (
    CreateInvoiceInput,
    UpdateInvoiceInput,
    InvoiceResponse,
    InvoiceDetailResponse,
    map_invoice_doc_to_response,
)
from app.modules.billing.schemas.payment_schemas import (
    map_payment_doc_to_response,
)

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
) -> InvoiceService:
    return InvoiceService(db, ctx)


@router.post("", response_model=SuccessEnvelope[InvoiceResponse], status_code=201)
async def create_invoice(
    input_data: CreateInvoiceInput,
    service: InvoiceService = Depends(_get_service),
):
    """
    Create an invoice with automatic GST computation.

    Pass seller_gstin and buyer_gstin in the request body.
    Line items are priced and taxed automatically.
    """
    doc = await service.create(input_data)
    mapped = map_invoice_doc_to_response(doc)
    return created(message="Invoice created successfully.", data=mapped)


@router.get("", response_model=PaginatedEnvelope[InvoiceResponse])
async def list_invoices(
    status: str = Query(None, description="Filter by status: draft, sent, paid, partial, overdue, void"),
    customer_ref_id: str = Query(None, description="Filter by customer ref_id"),
    source_app: str = Query(None, description="Filter by source app code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: InvoiceService = Depends(_get_service),
):
    """List invoices with optional filters."""
    documents, total = await service.list(
        status=status,
        customer_ref_id=customer_ref_id,
        source_app=source_app,
        skip=skip,
        limit=limit,
    )
    mapped = [map_invoice_doc_to_response(doc) for doc in documents]
    return paginated(message="Invoices retrieved.", data=mapped, total=total, skip=skip, limit=limit)


@router.get("/{invoice_number:path}", response_model=SuccessEnvelope[InvoiceDetailResponse])
async def get_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Get a single invoice with payment history."""
    doc, payments = await service.get(invoice_number)
    mapped_invoice = map_invoice_doc_to_response(doc)
    mapped_payments = [map_payment_doc_to_response(p) for p in payments]
    detail = InvoiceDetailResponse(
        **mapped_invoice.model_dump(),
        payment_history=mapped_payments,
    )
    return ok(message="Invoice retrieved.", data=detail)


@router.put("/{invoice_number:path}", response_model=SuccessEnvelope[InvoiceResponse])
async def update_invoice(
    invoice_number: str,
    input_data: UpdateInvoiceInput,
    service: InvoiceService = Depends(_get_service),
):
    """Update a draft invoice."""
    doc = await service.update(invoice_number, input_data)
    mapped = map_invoice_doc_to_response(doc)
    return ok(message="Invoice updated successfully.", data=mapped)


@router.post("/{invoice_number:path}/send", response_model=SuccessEnvelope[InvoiceResponse])
async def send_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Mark a draft invoice as sent."""
    doc = await service.send(invoice_number)
    mapped = map_invoice_doc_to_response(doc)
    return ok(message="Invoice marked as sent.", data=mapped)


@router.post("/{invoice_number:path}/void", response_model=SuccessEnvelope[InvoiceResponse])
async def void_invoice(
    invoice_number: str,
    service: InvoiceService = Depends(_get_service),
):
    """Void/cancel an invoice."""
    doc = await service.void(invoice_number)
    mapped = map_invoice_doc_to_response(doc)
    return ok(message="Invoice voided.", data=mapped)
