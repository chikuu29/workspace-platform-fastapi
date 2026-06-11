"""
OrderDoc — Beanie document for the orders collection.

Lightweight pre-invoice staging document. Captures billing intent
before committing to a financial document (invoice).

Domain apps create orders with validated line items and customer refs.
Confirming an order auto-generates a linked invoice.

Lifecycle: pending → confirmed → invoiced → completed → (cancelled)

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_ORDER,
    OrderStatus,
)
from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)
from app.modules.billing.documents.invoice_doc import LineItemEmbed


# ── Embedded Sub-Documents ───────────────────────────────────────────


class SourceRefEmbed(BaseModel):
    """
    Reference back to the domain app's source entity.

    Links the billing order to the originating business object.
    Each app passes its own ref_type + ref_id — billing doesn't
    interpret these, just stores them for traceability.

    Examples:
        Gym:        {app: "myGym", ref_type: "subscription", ref_id: "SUB-001"}
        Hostel:     {app: "myHostel", ref_type: "booking", ref_id: "BK-042"}
        Restaurant: {app: "myRestaurant", ref_type: "table_order", ref_id: "TO-007"}
    """

    app: str = ""
    ref_type: str = ""
    ref_id: str = ""


# ── Order Document ───────────────────────────────────────────────────


class OrderData(BaseModel):
    """Business fields for Order stored nested under 'data'."""
    order_number: str = ""
    customer_ref: Optional[CustomerRefEmbed] = None
    source_ref: Optional[SourceRefEmbed] = None
    line_items: List[LineItemEmbed] = Field(default_factory=list)
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = DEFAULT_CURRENCY
    seller_gstin: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""
    status: str = OrderStatus.PENDING
    invoice_ref: str = ""
    receipt_ref: str = ""
    source_app: str = ""
    notes: str = ""


class OrderDoc(BillingDocument):
    """
    Order Beanie document — stored in the orders collection.

    Lightweight pre-invoice staging document. Captures what the customer
    wants to buy before we commit to creating a financial document.
    """

    data: OrderData = Field(default_factory=OrderData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def order_number(self) -> str:
        return self.data.order_number

    @order_number.setter
    def order_number(self, value: str) -> None:
        self.data.order_number = value

    @property
    def customer_ref(self) -> Optional[CustomerRefEmbed]:
        return self.data.customer_ref

    @customer_ref.setter
    def customer_ref(self, value: Optional[CustomerRefEmbed]) -> None:
        self.data.customer_ref = value

    @property
    def source_ref(self) -> Optional[SourceRefEmbed]:
        return self.data.source_ref

    @source_ref.setter
    def source_ref(self, value: Optional[SourceRefEmbed]) -> None:
        self.data.source_ref = value

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
    def tax_amount(self) -> float:
        return self.data.tax_amount

    @tax_amount.setter
    def tax_amount(self, value: float) -> None:
        self.data.tax_amount = value

    @property
    def total(self) -> float:
        return self.data.total

    @total.setter
    def total(self, value: float) -> None:
        self.data.total = value

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
    def status(self) -> str:
        return self.data.status

    @status.setter
    def status(self, value: str) -> None:
        self.data.status = value

    @property
    def invoice_ref(self) -> str:
        return self.data.invoice_ref

    @invoice_ref.setter
    def invoice_ref(self, value: str) -> None:
        self.data.invoice_ref = value

    @property
    def receipt_ref(self) -> str:
        return self.data.receipt_ref

    @receipt_ref.setter
    def receipt_ref(self, value: str) -> None:
        self.data.receipt_ref = value

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

    class Settings:
        name = "orders"
        indexes = [
            # Unique order number lookup
            [("_org.org_id", 1), ("data.order_number", 1)],
            # Primary query: org + status + created date
            [("_org.org_id", 1), ("data.status", 1), ("_meta.created.at", -1)],
            # Customer history: org + customer ref_id
            [("_org.org_id", 1), ("data.customer_ref.ref_id", 1)],
            # Source app entity lookup
            [("_org.org_id", 1), ("data.source_ref.ref_id", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, order_number: str,
    ) -> Optional["OrderDoc"]:
        """Find an order by its unique number within the current org."""
        return await cls.org_find_one(ctx, {"data.order_number": order_number})

    @classmethod
    async def find_by_status(
        cls,
        ctx: OrgContext,
        status: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List["OrderDoc"]:
        """Find orders by status within the current org."""
        return await cls.org_find(
            ctx,
            {"data.status": status},
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    @classmethod
    async def find_by_source_ref(
        cls, ctx: OrgContext, ref_id: str,
    ) -> Optional["OrderDoc"]:
        """Find an order linked to a specific source app entity."""
        return await cls.org_find_one(ctx, {"data.source_ref.ref_id": ref_id})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> Optional["OrderDoc"]:
        """Find the order linked to a specific invoice."""
        return await cls.org_find_one(ctx, {"data.invoice_ref": invoice_ref})
