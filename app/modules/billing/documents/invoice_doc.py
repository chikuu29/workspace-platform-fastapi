"""
InvoiceDoc — Beanie document for the invoices collection.

Replaces the dataclass Invoice model + manual to_dict/from_dict.
Business fields are top-level typed attributes. Beanie + Pydantic
handle serialization, validation, and MongoDB interaction.

Inherits auto org-scoping from BillingDocument — every query is
automatically filtered by org_id without manual intervention.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_PAYMENT_TERMS,
    DiscountType,
    ENTITY_INVOICE,
    InvoiceStatus,
    InvoiceType,
)
from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)


# ── Embedded Sub-Documents ───────────────────────────────────────────
# These are stored as nested objects within the InvoiceDoc document.
# Unlike the old dataclass models, they're full Pydantic models with
# automatic serialization — no manual to_dict/from_dict needed.


class TaxBreakdownEmbed(BaseModel):
    """
    Itemized tax computation result — computed by TaxEngine.

    For intra-state: cgst + sgst = total_tax
    For inter-state: igst = total_tax
    """

    tax_type: str = "gst"
    tax_rate: float = 0.0
    taxable_amount: float = 0.0
    cgst_rate: float = 0.0
    cgst_amount: float = 0.0
    sgst_rate: float = 0.0
    sgst_amount: float = 0.0
    igst_rate: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    is_inter_state: bool = False


class LineItemEmbed(BaseModel):
    """
    A single line on an invoice — includes both input and computed fields.

    item_type distinguishes goods / service / subscription.
    source_item_code traces back to the originating app's catalog item.
    Computed fields (discount_amount, tax_amount, etc.) are set by
    the PricingEngine and TaxEngine.
    """

    # Item identity
    item_type: str = "service"
    source_item_code: str = ""
    description: str = ""
    hsn_sac_code: str = ""

    # Input fields (from the calling app — trusted)
    quantity: float = 1.0
    unit_price: float = 0.0
    discount_type: str = DiscountType.NONE
    discount_value: float = 0.0

    # Computed by PricingEngine
    discount_amount: float = 0.0

    # Computed by TaxEngine
    tax_category: str = ""
    tax_rate: float = 0.0
    tax_amount: float = 0.0

    # Computed totals
    taxable_amount: float = 0.0
    line_total: float = 0.0

    # Type-specific fields (optional — present depending on item_type)
    unit_of_measurement: Optional[str] = None   # Goods
    service_date: Optional[str] = None          # Service
    service_period_start: Optional[str] = None  # Service
    service_period_end: Optional[str] = None    # Service
    plan_code: Optional[str] = None             # Subscription
    billing_cycle: Optional[str] = None         # Subscription
    period_start: Optional[str] = None          # Subscription
    period_end: Optional[str] = None            # Subscription


# ── Invoice Document ─────────────────────────────────────────────────


class InvoiceDoc(BillingDocument):
    """
    Invoice Beanie document — stored in the invoices collection.

    Lifecycle: draft → sent → partial → paid → (void)

    All business fields are top-level (not nested under a `data` key).
    The _org and _meta envelope is inherited from BillingDocument.

    Usage:
        # Create
        doc = InvoiceDoc.create_for_org(ctx, entity_type=ENTITY_INVOICE, ...)
        await doc.insert()

        # Find (auto org-scoped)
        invoice = await InvoiceDoc.find_by_number(ctx, "INV/2026-27/0001")
        overdue = await InvoiceDoc.find_overdue(ctx, "2026-06-01")

        # Update
        invoice.status = InvoiceStatus.PAID
        await invoice.org_save(ctx)
    """

    # Identity
    invoice_number: Indexed(str, unique=True) = ""
    invoice_type: str = InvoiceType.STANDARD

    # Customer (resolved by the calling app module)
    customer_ref: Optional[CustomerRefEmbed] = None

    # Line items (pricing + tax computed by engines)
    line_items: List[LineItemEmbed] = Field(default_factory=list)

    # Financials (all server-computed — never from client)
    subtotal: float = 0.0
    tax_breakdown: Optional[TaxBreakdownEmbed] = None
    total: float = 0.0
    amount_paid: float = 0.0
    balance_due: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # GST context (passed per-invoice by the calling app)
    seller_gstin: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""
    is_inter_state: bool = False

    # Status & dates
    status: str = InvoiceStatus.DRAFT
    issue_date: str = ""
    due_date: str = ""
    payment_terms: str = DEFAULT_PAYMENT_TERMS

    # Source tracking — which app generated this invoice
    source_app: str = ""

    # Notes
    notes: str = ""
    terms_and_conditions: str = ""

    class Settings:
        # Collection name in MongoDB
        name = "invoices"
        # Compound indexes for common query patterns
        indexes = [
            # Overdue lookup: org + status + due_date
            [("_org.org_id", 1), ("status", 1), ("due_date", 1)],
            # Customer history: org + customer ref_id
            [("_org.org_id", 1), ("customer_ref.ref_id", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, invoice_number: str
    ) -> Optional["InvoiceDoc"]:
        """Find an invoice by its unique number within the current org."""
        return await cls.org_find_one(ctx, {"invoice_number": invoice_number})

    @classmethod
    async def find_by_customer(
        cls,
        ctx: OrgContext,
        ref_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List["InvoiceDoc"]:
        """Find invoices for a specific customer."""
        return await cls.org_find(
            ctx,
            {"customer_ref.ref_id": ref_id},
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    @classmethod
    async def find_overdue(
        cls,
        ctx: OrgContext,
        as_of_date: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List["InvoiceDoc"]:
        """Find invoices past due date that are not fully paid."""
        return await cls.org_find(
            ctx,
            {
                "status": {"$in": [InvoiceStatus.SENT, InvoiceStatus.PARTIAL]},
                "due_date": {"$lt": as_of_date},
            },
            sort=[("due_date", 1)],
            skip=skip,
            limit=limit,
        )
