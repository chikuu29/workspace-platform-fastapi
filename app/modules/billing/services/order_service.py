"""
Order Service — pre-invoice billing order lifecycle.

Domain apps create orders to capture billing intent before
committing to financial documents. Confirming an order
auto-generates a linked invoice.

Lifecycle: pending → confirmed → invoiced → completed → (cancelled)

Inherits from BaseBillingService for shared infrastructure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, not_found
from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_ORDER,
    OrderStatus,
)
from app.modules.billing.documents.base import CustomerRefEmbed
from app.modules.billing.documents.invoice_doc import (
    InvoiceDoc,
    LineItemEmbed,
    TaxBreakdownEmbed,
)
from app.modules.billing.documents.order_doc import (
    OrderDoc,
    SourceRefEmbed,
)
from app.modules.billing.engines.pricing_engine import compute_line_pricing
from app.modules.billing.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
)
from app.modules.billing.schemas.order_schemas import CreateOrderInput
from app.modules.billing.services.base import BaseBillingService


class OrderService(BaseBillingService):
    """
    Order lifecycle management — pre-invoice staging.

    Domain apps create orders with pre-validated line items.
    Billing computes pricing, tax, and totals. Confirming an
    order auto-generates a linked invoice.

    Public methods:
        create(input_data)           — create a billing order
        confirm(order_number)        — confirm → auto-creates invoice
        cancel(order_number, reason) — cancel a pending order
        get(order_number)            — get a single order
        list(...)                    — list orders with filters
    """

    # ── BaseBillingService Abstract Properties ───────────────────

    @property
    def service_name(self) -> str:
        return "orders"

    @property
    def entity_type(self) -> str:
        return ENTITY_ORDER

    @property
    def number_prefix(self) -> str:
        return "ORD"

    # ── Public Methods ───────────────────────────────────────────

    async def create(self, input_data: CreateOrderInput) -> OrderDoc:
        """
        Create a billing order with line-item pricing + tax computation.

        The domain app has ALREADY validated items and prices.
        Billing computes: tax, discounts, totals, order number.
        Status starts as PENDING.
        """
        seller_gstin = input_data.seller_gstin or ""
        buyer_gstin = input_data.buyer_gstin or ""
        place_of_supply = input_data.place_of_supply or ""

        # Compute line items
        computed_items: List[LineItemEmbed] = []
        line_tax_inputs: list[tuple[float, str]] = []

        for item in input_data.line_items:
            qty = item.quantity
            price = item.unit_price
            disc_type = item.discount_type
            disc_value = item.discount_value
            tax_cat = item.tax_category

            # Pricing: qty × price − discount
            line_calc = compute_line_pricing(
                quantity=qty,
                unit_price=price,
                discount_type=disc_type,
                discount_value=disc_value,
                tax_amount=0.0,
            )

            # Tax: GST on taxable amount
            line_tax = compute_line_tax(
                taxable_amount=line_calc.taxable_amount,
                tax_category=tax_cat,
                seller_gstin=seller_gstin,
                place_of_supply=place_of_supply or buyer_gstin,
            )

            # Re-compute with actual tax
            final_calc = compute_line_pricing(
                quantity=qty,
                unit_price=price,
                discount_type=disc_type,
                discount_value=disc_value,
                tax_amount=line_tax.total_tax,
            )

            item_dump = item.model_dump(exclude_unset=False)

            computed_items.append(
                LineItemEmbed(
                    item_type=item.item_type,
                    source_item_code=item.source_item_code or "",
                    description=item.description,
                    hsn_sac_code=item.hsn_sac_code or "",
                    quantity=qty,
                    unit_price=price,
                    discount_type=disc_type,
                    discount_value=disc_value,
                    discount_amount=final_calc.discount_amount,
                    tax_category=tax_cat,
                    tax_rate=line_tax.tax_rate,
                    tax_amount=line_tax.total_tax,
                    taxable_amount=final_calc.taxable_amount,
                    line_total=final_calc.line_total,
                    unit_of_measurement=item_dump.get("unit_of_measurement"),
                    service_date=item_dump.get("service_date"),
                    service_period_start=item_dump.get("service_period_start"),
                    service_period_end=item_dump.get("service_period_end"),
                    plan_code=item_dump.get("plan_code"),
                    billing_cycle=item_dump.get("billing_cycle"),
                    period_start=item_dump.get("period_start"),
                    period_end=item_dump.get("period_end"),
                )
            )

            line_tax_inputs.append((final_calc.taxable_amount, tax_cat))

        # Aggregate totals
        agg_tax = compute_invoice_tax(
            line_taxable_amounts=line_tax_inputs,
            seller_gstin=seller_gstin,
            place_of_supply=place_of_supply or buyer_gstin,
        )

        subtotal = round(sum(li.taxable_amount for li in computed_items), 2)
        total = round(subtotal + agg_tax.total_tax, 2)

        # Generate order number
        order_number = await self._generate_number()

        # Build source reference embed
        source_ref_data = input_data.source_ref or {}
        source_ref = SourceRefEmbed(
            app=source_ref_data.get("app", self._ctx.app_code),
            ref_type=source_ref_data.get("ref_type", ""),
            ref_id=source_ref_data.get("ref_id", ""),
        )

        # Build customer reference embed
        customer_ref = CustomerRefEmbed(
            ref_type=input_data.customer_ref.ref_type,
            ref_id=input_data.customer_ref.ref_id,
            name=input_data.customer_ref.name,
            email=input_data.customer_ref.email,
            phone=input_data.customer_ref.phone,
            gstin=input_data.customer_ref.gstin,
        )

        # Create order document
        doc = OrderDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_ORDER,
            record_id=order_number,
            order_number=order_number,
            customer_ref=customer_ref,
            source_ref=source_ref,
            line_items=computed_items,
            subtotal=subtotal,
            tax_amount=agg_tax.total_tax,
            total=total,
            currency=input_data.currency or DEFAULT_CURRENCY,
            seller_gstin=seller_gstin,
            buyer_gstin=buyer_gstin,
            place_of_supply=place_of_supply,
            status=OrderStatus.PENDING,
            source_app=self._ctx.app_code,
            notes=input_data.notes or "",
        )

        await doc.insert()

        self._logger.info(
            "Created order %s total=%.2f org=%s app=%s",
            order_number, total, self._ctx.org_id, self._ctx.app_code,
        )
        return doc

    async def confirm(
        self, order_number: str,
    ) -> Tuple[OrderDoc, InvoiceDoc]:
        """
        Confirm an order → auto-creates an invoice.

        Transitions: PENDING → CONFIRMED → INVOICED
        Side effect: creates InvoiceDoc linked to this order.

        Returns:
            Tuple of (updated OrderDoc, new InvoiceDoc).
        """
        doc = await OrderDoc.find_by_number(self._ctx, order_number)
        if not doc:
            not_found(message=f"Order '{order_number}' not found.")

        if doc.status != OrderStatus.PENDING:
            bad_request(
                message=f"Cannot confirm order with status '{doc.status}'. "
                        f"Only pending orders can be confirmed.",
            )

        # Create invoice from order
        from app.modules.billing.services.invoice_service import InvoiceService

        invoice_svc = InvoiceService(self._db, self._ctx)
        invoice_doc = await invoice_svc.create_from_order(doc)

        # Update order status and link to invoice
        doc.status = OrderStatus.INVOICED
        doc.invoice_ref = invoice_doc.invoice_number
        await doc.org_save(self._ctx)

        self._logger.info(
            "Confirmed order %s → invoice %s org=%s",
            order_number, invoice_doc.invoice_number, self._ctx.org_id,
        )
        return doc, invoice_doc

    async def cancel(
        self, order_number: str, reason: str = "",
    ) -> OrderDoc:
        """
        Cancel a pending order.

        Only PENDING orders can be cancelled. Confirmed/invoiced
        orders must be voided through the invoice void flow.
        """
        doc = await OrderDoc.find_by_number(self._ctx, order_number)
        if not doc:
            not_found(message=f"Order '{order_number}' not found.")

        if doc.status != OrderStatus.PENDING:
            bad_request(
                message=f"Cannot cancel order with status '{doc.status}'. "
                        f"Only pending orders can be cancelled.",
            )

        doc.status = OrderStatus.CANCELLED
        if reason:
            doc.notes = f"{doc.notes}\nCancellation reason: {reason}".strip()
        await doc.org_save(self._ctx)

        self._logger.info(
            "Cancelled order %s reason='%s' org=%s",
            order_number, reason, self._ctx.org_id,
        )
        return doc

    async def get(self, order_number: str) -> OrderDoc:
        """Get a single order by its number."""
        doc = await OrderDoc.find_by_number(self._ctx, order_number)
        if not doc:
            not_found(message=f"Order '{order_number}' not found.")
        return doc

    async def list(
        self,
        *,
        status: Optional[str] = None,
        customer_ref_id: Optional[str] = None,
        source_ref_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[OrderDoc], int]:
        """List orders with optional filters."""
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if customer_ref_id:
            query["customer_ref.ref_id"] = customer_ref_id
        if source_ref_id:
            query["source_ref.ref_id"] = source_ref_id

        documents = await OrderDoc.org_find(
            self._ctx,
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await OrderDoc.org_count(self._ctx, query)
        return documents, total
