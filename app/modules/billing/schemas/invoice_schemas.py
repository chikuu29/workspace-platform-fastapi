"""
Invoice request (internal contract) and response (API) schemas.

Request schemas (CreateInvoiceInput, UpdateInvoiceInput) are internal
contracts — used by app modules (gym, hostel) to send validated data
to the billing service. The app already verified items and prices.

Response schemas (InvoiceResponse) are the predictable API shape
returned to the frontend for invoice display.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.modules.billing.documents.invoice_doc import InvoiceDoc

from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_PAYMENT_TERMS,
    InvoiceType,
)
from app.modules.billing.schemas.common import (
    AuditInfoResponse,
    CustomerRefSchema,
    TaxBreakdownResponse,
)
from app.modules.billing.schemas.line_items import (
    LineItemInput,
    LineItemResponse,
)
from app.modules.billing.schemas.payment_schemas import PaymentResponse


# ── Internal Request (App Module → Billing Service) ──────────────────


class CreateInvoiceInput(BaseModel):
    """
    Internal contract: what an app module passes to billing to create an invoice.

    The app has ALREADY validated:
      - Customer exists in its own data
      - Items exist and prices are correct
      - GSTIN format is valid

    Billing trusts this data and computes tax, discounts, and totals.

    Example usage from gym:
        billing_input = CreateInvoiceInput(
            customer_ref=CustomerRefSchema(ref_type="member", ref_id="M-1", name="Alice"),
            line_items=[ServiceLineItem(item_type="service", unit_price=5000, ...)],
            seller_gstin="29AABCU9603R1ZM",
        )
        invoice_svc = InvoiceService(db, ctx)
        result = await invoice_svc.create_invoice(billing_input)
    """

    customer_ref: CustomerRefSchema
    line_items: List[LineItemInput] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="At least one line item required. Max 100 per invoice.",
    )

    # GST context — passed per-invoice, not pre-configured
    seller_gstin: str = Field(
        ...,
        pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$",
        description="Seller's GSTIN (required for GST computation)",
    )
    buyer_gstin: str = Field(
        "",
        pattern=r"^$|^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$",
        description="Buyer's GSTIN (optional for B2C transactions)",
    )
    place_of_supply: str = Field(
        "",
        max_length=2,
        description="2-digit state code — determines CGST/SGST vs IGST",
    )

    # Optional overrides
    invoice_type: str = InvoiceType.STANDARD
    due_date: str = Field("", description="Due date (ISO format: YYYY-MM-DD)")
    payment_terms: str = DEFAULT_PAYMENT_TERMS
    currency: str = DEFAULT_CURRENCY
    notes: str = Field("", max_length=2000)
    terms_and_conditions: str = Field("", max_length=5000)


class UpdateInvoiceInput(BaseModel):
    """
    Partial update for draft invoices only.

    Only provided fields are updated — None fields are left unchanged.
    Line items replacement triggers full re-computation of pricing + tax.
    """

    line_items: Optional[List[LineItemInput]] = Field(
        None,
        min_length=1,
        max_length=100,
    )
    due_date: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=2000)
    terms_and_conditions: Optional[str] = Field(None, max_length=5000)


# ── API Response (Billing → Frontend) ────────────────────────────────


class InvoiceResponse(BaseModel):
    """
    Predictable invoice response shape for frontend consumers.

    Every field is typed and documented. The frontend can rely on
    this exact structure — no more raw dict unpredictability.
    """

    # Identity
    invoice_number: str
    invoice_type: str

    # Customer
    customer_ref: CustomerRefSchema

    # Line items (with server-computed fields)
    line_items: List[LineItemResponse]

    # Financials (all server-computed — never from client)
    subtotal: float
    tax_breakdown: TaxBreakdownResponse
    total: float
    amount_paid: float
    balance_due: float
    currency: str

    # GST
    seller_gstin: str
    buyer_gstin: str
    place_of_supply: str
    is_inter_state: bool

    # Status & dates
    status: str
    issue_date: str
    due_date: str
    payment_terms: str

    # Source app
    source_app: str

    # Notes
    notes: str
    terms_and_conditions: str

    # Audit trail
    audit: AuditInfoResponse


class InvoiceDetailResponse(InvoiceResponse):
    """Detailed invoice response including payment history."""
    payment_history: List[PaymentResponse] = Field(default_factory=list)


def map_invoice_doc_to_response(doc: InvoiceDoc) -> InvoiceResponse:
    """Map a Beanie InvoiceDoc to an InvoiceResponse schema."""
    return InvoiceResponse(
        invoice_number=doc.invoice_number,
        invoice_type=doc.invoice_type,
        customer_ref=CustomerRefSchema(
            ref_type=doc.customer_ref.ref_type if doc.customer_ref else "customer",
            ref_id=doc.customer_ref.ref_id if doc.customer_ref else "",
            name=doc.customer_ref.name if doc.customer_ref else "",
            email=doc.customer_ref.email if doc.customer_ref else "",
            phone=doc.customer_ref.phone if doc.customer_ref else "",
            gstin=doc.customer_ref.gstin if doc.customer_ref else "",
        ),
        line_items=[
            LineItemResponse(
                item_type=li.item_type,
                source_item_code=li.source_item_code or "",
                description=li.description,
                hsn_sac_code=li.hsn_sac_code or "",
                quantity=li.quantity,
                unit_price=li.unit_price,
                discount_type=li.discount_type,
                discount_value=li.discount_value,
                discount_amount=li.discount_amount,
                tax_category=li.tax_category,
                tax_rate=li.tax_rate,
                tax_amount=li.tax_amount,
                taxable_amount=li.taxable_amount,
                line_total=li.line_total,
            )
            for li in doc.line_items
        ],
        subtotal=doc.subtotal,
        tax_breakdown=TaxBreakdownResponse(
            tax_type=doc.tax_breakdown.tax_type if doc.tax_breakdown else "gst",
            tax_rate=doc.tax_breakdown.tax_rate if doc.tax_breakdown else 0.0,
            taxable_amount=doc.tax_breakdown.taxable_amount if doc.tax_breakdown else 0.0,
            cgst_rate=doc.tax_breakdown.cgst_rate if doc.tax_breakdown else 0.0,
            cgst_amount=doc.tax_breakdown.cgst_amount if doc.tax_breakdown else 0.0,
            sgst_rate=doc.tax_breakdown.sgst_rate if doc.tax_breakdown else 0.0,
            sgst_amount=doc.tax_breakdown.sgst_amount if doc.tax_breakdown else 0.0,
            igst_rate=doc.tax_breakdown.igst_rate if doc.tax_breakdown else 0.0,
            igst_amount=doc.tax_breakdown.igst_amount if doc.tax_breakdown else 0.0,
            total_tax=doc.tax_breakdown.total_tax if doc.tax_breakdown else 0.0,
            is_inter_state=doc.tax_breakdown.is_inter_state if doc.tax_breakdown else False,
        ),
        total=doc.total,
        amount_paid=doc.amount_paid,
        balance_due=doc.balance_due,
        currency=doc.currency,
        seller_gstin=doc.seller_gstin,
        buyer_gstin=doc.buyer_gstin,
        place_of_supply=doc.place_of_supply,
        is_inter_state=doc.is_inter_state,
        status=doc.status,
        issue_date=doc.issue_date,
        due_date=doc.due_date,
        payment_terms=doc.payment_terms,
        source_app=doc.source_app,
        notes=doc.notes or "",
        terms_and_conditions=doc.terms_and_conditions or "",
        audit=AuditInfoResponse(
            record_id=doc.meta_info.record_id,
            version=doc.meta_info.version,
            created_at=doc.meta_info.created.at,
            created_by=doc.meta_info.created.by,
            updated_at=doc.meta_info.updated.at if doc.meta_info.updated else None,
            updated_by=doc.meta_info.updated.by if doc.meta_info.updated else None,
        ),
    )
