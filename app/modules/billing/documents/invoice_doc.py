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


class InvoiceData(BaseModel):
    """Business fields for Invoice stored nested under 'data'."""
    invoice_number: str = ""
    invoice_type: str = InvoiceType.STANDARD
    customer_ref: Optional[CustomerRefEmbed] = None
    line_items: List[LineItemEmbed] = Field(default_factory=list)
    subtotal: float = 0.0
    tax_breakdown: Optional[TaxBreakdownEmbed] = None
    total: float = 0.0
    amount_paid: float = 0.0
    balance_due: float = 0.0
    currency: str = DEFAULT_CURRENCY
    seller_gstin: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""
    is_inter_state: bool = False
    status: str = InvoiceStatus.DRAFT
    issue_date: str = ""
    due_date: str = ""
    payment_terms: str = DEFAULT_PAYMENT_TERMS
    source_app: str = ""
    notes: str = ""
    terms_and_conditions: str = ""


class InvoiceDoc(BillingDocument):
    """
    Invoice Beanie document — stored in the invoices collection.

    Lifecycle: draft → sent → partial → paid → (void)
    """

    data: InvoiceData = Field(default_factory=InvoiceData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def invoice_number(self) -> str:
        return self.data.invoice_number

    @invoice_number.setter
    def invoice_number(self, value: str) -> None:
        self.data.invoice_number = value

    @property
    def invoice_type(self) -> str:
        return self.data.invoice_type

    @invoice_type.setter
    def invoice_type(self, value: str) -> None:
        self.data.invoice_type = value

    @property
    def customer_ref(self) -> Optional[CustomerRefEmbed]:
        return self.data.customer_ref

    @customer_ref.setter
    def customer_ref(self, value: Optional[CustomerRefEmbed]) -> None:
        self.data.customer_ref = value

    @property
    def line_items(self) -> List[LineItemEmbed]:
        return self.data.line_items

    @line_items.setter
    def line_items(self, value: List[LineItemEmbed]) -> None:
        self.data.line_items = value

    @property
    def subtotal(self) -> float:
        return self.data.subtotal

    @subtotal.setter
    def subtotal(self, value: float) -> None:
        self.data.subtotal = value

    @property
    def tax_breakdown(self) -> Optional[TaxBreakdownEmbed]:
        return self.data.tax_breakdown

    @tax_breakdown.setter
    def tax_breakdown(self, value: Optional[TaxBreakdownEmbed]) -> None:
        self.data.tax_breakdown = value

    @property
    def total(self) -> float:
        return self.data.total

    @total.setter
    def total(self, value: float) -> None:
        self.data.total = value

    @property
    def amount_paid(self) -> float:
        return self.data.amount_paid

    @amount_paid.setter
    def amount_paid(self, value: float) -> None:
        self.data.amount_paid = value

    @property
    def balance_due(self) -> float:
        return self.data.balance_due

    @balance_due.setter
    def balance_due(self, value: float) -> None:
        self.data.balance_due = value

    @property
    def currency(self) -> str:
        return self.data.currency

    @currency.setter
    def currency(self, value: str) -> None:
        self.data.currency = value

    @property
    def seller_gstin(self) -> str:
        return self.data.seller_gstin

    @seller_gstin.setter
    def seller_gstin(self, value: str) -> None:
        self.data.seller_gstin = value

    @property
    def buyer_gstin(self) -> str:
        return self.data.buyer_gstin

    @buyer_gstin.setter
    def buyer_gstin(self, value: str) -> None:
        self.data.buyer_gstin = value

    @property
    def place_of_supply(self) -> str:
        return self.data.place_of_supply

    @place_of_supply.setter
    def place_of_supply(self, value: str) -> None:
        self.data.place_of_supply = value

    @property
    def is_inter_state(self) -> bool:
        return self.data.is_inter_state

    @is_inter_state.setter
    def is_inter_state(self, value: bool) -> None:
        self.data.is_inter_state = value

    @property
    def status(self) -> str:
        return self.data.status

    @status.setter
    def status(self, value: str) -> None:
        self.data.status = value

    @property
    def issue_date(self) -> str:
        return self.data.issue_date

    @issue_date.setter
    def issue_date(self, value: str) -> None:
        self.data.issue_date = value

    @property
    def due_date(self) -> str:
        return self.data.due_date

    @due_date.setter
    def due_date(self, value: str) -> None:
        self.data.due_date = value

    @property
    def payment_terms(self) -> str:
        return self.data.payment_terms

    @payment_terms.setter
    def payment_terms(self, value: str) -> None:
        self.data.payment_terms = value

    @property
    def source_app(self) -> str:
        return self.data.source_app

    @source_app.setter
    def source_app(self, value: str) -> None:
        self.data.source_app = value

    @property
    def notes(self) -> str:
        return self.data.notes

    @notes.setter
    def notes(self, value: str) -> None:
        self.data.notes = value

    @property
    def terms_and_conditions(self) -> str:
        return self.data.terms_and_conditions

    @terms_and_conditions.setter
    def terms_and_conditions(self, value: str) -> None:
        self.data.terms_and_conditions = value

    class Settings:
        # Collection name in MongoDB
        name = "invoices"
        # Compound indexes for common query patterns
        indexes = [
            # Unique invoice number lookup
            [("_org.org_id", 1), ("data.invoice_number", 1)],
            # Overdue lookup: org + status + due_date
            [("_org.org_id", 1), ("data.status", 1), ("data.due_date", 1)],
            # Customer history: org + customer ref_id
            [("_org.org_id", 1), ("data.customer_ref.ref_id", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, invoice_number: str
    ) -> Optional["InvoiceDoc"]:
        """Find an invoice by its unique number within the current org."""
        return await cls.org_find_one(ctx, {"data.invoice_number": invoice_number})

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
            {"data.customer_ref.ref_id": ref_id},
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
                "data.status": {"$in": [InvoiceStatus.SENT, InvoiceStatus.PARTIAL]},
                "data.due_date": {"$lt": as_of_date},
            },
            sort=[("data.due_date", 1)],
            skip=skip,
            limit=limit,
        )
