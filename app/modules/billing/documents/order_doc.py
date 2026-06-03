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


class OrderDoc(BillingDocument):
    """
    Order Beanie document — stored in the orders collection.

    Lightweight pre-invoice staging document. Captures what the customer
    wants to buy before we commit to creating a financial document.

    The domain app creates the order after validating business rules
    (member exists, plan active, price correct). Billing computes
    tax, discounts, and totals.

    Lifecycle: pending → confirmed → invoiced → completed → (cancelled)

    Usage:
        doc = OrderDoc.create_for_org(ctx, entity_type=ENTITY_ORDER, ...)
        await doc.insert()

        order = await OrderDoc.find_by_number(ctx, "ORD/2026-27/0001")
        pending = await OrderDoc.find_by_status(ctx, OrderStatus.PENDING)
    """

    # Identity
    order_number: Indexed(str, unique=True) = ""

    # Customer (resolved by the calling app module)
    customer_ref: Optional[CustomerRefEmbed] = None

    # Source app reference — links to domain app's entity
    source_ref: Optional[SourceRefEmbed] = None

    # Line items (same structure as invoice line items)
    line_items: List[LineItemEmbed] = Field(default_factory=list)

    # Financials (computed from line items by pricing + tax engines)
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # GST context (passed per-order by the calling app)
    seller_gstin: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""

    # Status lifecycle
    status: str = OrderStatus.PENDING

    # Linked billing documents (populated as order progresses)
    invoice_ref: str = ""       # Set when invoice is generated (confirm)
    receipt_ref: str = ""       # Set when receipt is generated (full payment)

    # Source tracking — which app generated this order
    source_app: str = ""

    # Notes
    notes: str = ""

    class Settings:
        name = "orders"
        indexes = [
            # Primary query: org + status + created date
            [("_org.org_id", 1), ("status", 1), ("_meta.created.at", -1)],
            # Customer history: org + customer ref_id
            [("_org.org_id", 1), ("customer_ref.ref_id", 1)],
            # Source app entity lookup
            [("_org.org_id", 1), ("source_ref.ref_id", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_by_number(
        cls, ctx: OrgContext, order_number: str,
    ) -> Optional["OrderDoc"]:
        """Find an order by its unique number within the current org."""
        return await cls.org_find_one(ctx, {"order_number": order_number})

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
            {"status": status},
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    @classmethod
    async def find_by_source_ref(
        cls, ctx: OrgContext, ref_id: str,
    ) -> Optional["OrderDoc"]:
        """Find an order linked to a specific source app entity."""
        return await cls.org_find_one(ctx, {"source_ref.ref_id": ref_id})

    @classmethod
    async def find_by_invoice(
        cls, ctx: OrgContext, invoice_ref: str,
    ) -> Optional["OrderDoc"]:
        """Find the order linked to a specific invoice."""
        return await cls.org_find_one(ctx, {"invoice_ref": invoice_ref})
