"""
Invoice Service — the core billing workflow.

Orchestrates invoice creation with:
 1. Line-item pricing (PricingEngine)
 2. GST tax computation (TaxEngine) — GSTIN passed via API
 3. Invoice numbering (Indian financial year format: INV/2026-27/0001)
 4. Status lifecycle management (draft → sent → partial → paid)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, not_found
from app.core.context import OrgContext
from app.core.logger import create_logger
from app.db.org_sequence import OrgSequenceService
from app.modules.billing_management.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_PAYMENT_TERMS,
    ENTITY_INVOICE,
    InvoiceStatus,
)
from app.modules.billing_management.engines.pricing_engine import (
    compute_line_pricing,
)
from app.modules.billing_management.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
)
from app.modules.billing_management.documents.invoice_doc import (
    InvoiceDoc,
    CustomerRefEmbed,
    TaxBreakdownEmbed,
    LineItemEmbed,
)
from app.modules.billing_management.documents.payment_doc import PaymentDoc
from app.modules.billing_management.schemas.invoice_schemas import (
    CreateInvoiceInput,
    UpdateInvoiceInput,
)

logger = create_logger("billing.invoice_service")


def _indian_financial_year() -> str:
    """
    Derive the Indian financial year string for invoice numbering.

    Indian FY runs April → March.
    May 2026 → "2026-27"
    Feb 2027 → "2026-27"
    """
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    if month >= 4:
        # April onwards → current year to next year
        return f"{year}-{str(year + 1)[-2:]}"
    else:
        # Jan-Mar → previous year to current year
        return f"{year - 1}-{str(year)[-2:]}"


class InvoiceService:
    """Business logic for the invoice lifecycle using Beanie."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx

    async def _generate_invoice_number(self) -> str:
        """
        Generate Indian financial-year invoice number.

        Format: INV/2026-27/0001
        Uses OrgSequenceService for atomic counter per org+app+FY.
        """
        fy = _indian_financial_year()
        seq = OrgSequenceService(self._db, self._ctx)
        # Use FY as part of the counter key to reset numbering each FY
        counter_id = f"billing_invoice:{fy}"
        doc = await seq._sequences.find_one_and_update(
            {"_id": f"{self._ctx.org_name}:{self._ctx.app_code}:{counter_id}"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        
        invoice_number = f"INV/{fy}/{doc['seq']:04d}"
        print(f"Invoice Number: {invoice_number}")
        return invoice_number

    async def create_invoice(self, input_data: CreateInvoiceInput) -> InvoiceDoc:
        """
        Create an invoice with full tax + pricing computation.

        Price is TRUSTED — the calling app already verified it.
        Billing computes: tax, discounts, totals, invoice number.
        """
        # ── Process each line item ────────────────────────────────────
        computed_items: List[LineItemEmbed] = []
        line_tax_inputs: list[tuple[float, str]] = []

        seller_gstin = input_data.seller_gstin
        buyer_gstin = input_data.buyer_gstin or ""
        place_of_supply = input_data.place_of_supply or ""

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

            # Re-compute with actual tax amount
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

        # ── Aggregate invoice totals ──────────────────────────────────
        agg_tax = compute_invoice_tax(
            line_taxable_amounts=line_tax_inputs,
            seller_gstin=seller_gstin,
            place_of_supply=place_of_supply or buyer_gstin,
        )

        subtotal = sum(li.taxable_amount for li in computed_items)
        total = round(subtotal + agg_tax.total_tax, 2)

        # ── Generate invoice number ───────────────────────────────────
        invoice_number = await self._generate_invoice_number()

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        due_date_str = input_data.due_date if input_data.due_date else now_str

        # Build Beanie document
        doc = InvoiceDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_INVOICE,
            record_id=invoice_number,
            invoice_number=invoice_number,
            invoice_type=input_data.invoice_type,
            customer_ref=CustomerRefEmbed(
                ref_type=input_data.customer_ref.ref_type,
                ref_id=input_data.customer_ref.ref_id,
                name=input_data.customer_ref.name,
                email=input_data.customer_ref.email,
                phone=input_data.customer_ref.phone,
                gstin=input_data.customer_ref.gstin,
            ),
            line_items=computed_items,
            subtotal=round(subtotal, 2),
            tax_breakdown=TaxBreakdownEmbed(
                tax_type=agg_tax.tax_type,
                tax_rate=agg_tax.tax_rate,
                taxable_amount=agg_tax.taxable_amount,
                cgst_rate=agg_tax.cgst_rate,
                cgst_amount=agg_tax.cgst_amount,
                sgst_rate=agg_tax.sgst_rate,
                sgst_amount=agg_tax.sgst_amount,
                igst_rate=agg_tax.igst_rate,
                igst_amount=agg_tax.igst_amount,
                total_tax=agg_tax.total_tax,
                is_inter_state=agg_tax.is_inter_state,
            ),
            total=total,
            amount_paid=0.0,
            balance_due=total,
            currency=input_data.currency,
            seller_gstin=seller_gstin,
            buyer_gstin=buyer_gstin,
            place_of_supply=place_of_supply,
            is_inter_state=agg_tax.is_inter_state,
            status=InvoiceStatus.DRAFT,
            issue_date=now_str,
            due_date=due_date_str,
            payment_terms=input_data.payment_terms,
            source_app=self._ctx.app_code,
            notes=input_data.notes,
            terms_and_conditions=input_data.terms_and_conditions,
        )

        await doc.insert()

        logger.info(
            "Created invoice %s total=%.2f org=%s app=%s",
            invoice_number, total, self._ctx.org_id, self._ctx.app_code,
        )
        return doc

    async def list_invoices(
        self,
        *,
        status: Optional[str] = None,
        customer_ref_id: Optional[str] = None,
        source_app: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[InvoiceDoc], int]:
        """List invoices with optional filters."""
        query: Dict[str, Any] = {}
        if status:
            query["status"] = status
        if customer_ref_id:
            query["customer_ref.ref_id"] = customer_ref_id
        if source_app:
            query["source_app"] = source_app

        documents = await InvoiceDoc.org_find(
            self._ctx,
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await InvoiceDoc.org_count(self._ctx, query)
        return documents, total

    async def get_invoice(self, invoice_number: str) -> tuple[InvoiceDoc, List[PaymentDoc]]:
        """Get a single invoice with payment history."""
        doc = await InvoiceDoc.find_by_number(self._ctx, invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        payments = await PaymentDoc.find_by_invoice(self._ctx, invoice_number)
        return doc, payments

    async def update_invoice(
        self, invoice_number: str, input_data: UpdateInvoiceInput,
    ) -> InvoiceDoc:
        """Update a draft invoice. Only draft invoices can be edited."""
        doc = await InvoiceDoc.find_by_number(self._ctx, invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        if doc.status != InvoiceStatus.DRAFT:
            bad_request(
                message="Only draft invoices can be edited. "
                        f"Current status: {doc.status}."
            )

        # Update fields if provided
        if input_data.due_date is not None:
            doc.due_date = input_data.due_date
        if input_data.payment_terms is not None:
            doc.payment_terms = input_data.payment_terms
        if input_data.notes is not None:
            doc.notes = input_data.notes
        if input_data.terms_and_conditions is not None:
            doc.terms_and_conditions = input_data.terms_and_conditions

        if input_data.line_items is not None:
            # Recompute line items
            computed_items: List[LineItemEmbed] = []
            line_tax_inputs: list[tuple[float, str]] = []

            seller_gstin = doc.seller_gstin
            buyer_gstin = doc.buyer_gstin
            place_of_supply = doc.place_of_supply

            for item in input_data.line_items:
                qty = item.quantity
                price = item.unit_price
                disc_type = item.discount_type
                disc_value = item.discount_value
                tax_cat = item.tax_category

                line_calc = compute_line_pricing(
                    quantity=qty,
                    unit_price=price,
                    discount_type=disc_type,
                    discount_value=disc_value,
                    tax_amount=0.0,
                )

                line_tax = compute_line_tax(
                    taxable_amount=line_calc.taxable_amount,
                    tax_category=tax_cat,
                    seller_gstin=seller_gstin,
                    place_of_supply=place_of_supply or buyer_gstin,
                )

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

            agg_tax = compute_invoice_tax(
                line_taxable_amounts=line_tax_inputs,
                seller_gstin=seller_gstin,
                place_of_supply=place_of_supply or buyer_gstin,
            )

            subtotal = sum(li.taxable_amount for li in computed_items)
            total = round(subtotal + agg_tax.total_tax, 2)

            doc.line_items = computed_items
            doc.subtotal = round(subtotal, 2)
            doc.tax_breakdown = TaxBreakdownEmbed(
                tax_type=agg_tax.tax_type,
                tax_rate=agg_tax.tax_rate,
                taxable_amount=agg_tax.taxable_amount,
                cgst_rate=agg_tax.cgst_rate,
                cgst_amount=agg_tax.cgst_amount,
                sgst_rate=agg_tax.sgst_rate,
                sgst_amount=agg_tax.sgst_amount,
                igst_rate=agg_tax.igst_rate,
                igst_amount=agg_tax.igst_amount,
                total_tax=agg_tax.total_tax,
                is_inter_state=agg_tax.is_inter_state,
            )
            doc.total = total
            doc.balance_due = round(total - doc.amount_paid, 2)
            doc.is_inter_state = agg_tax.is_inter_state

        await doc.org_save(self._ctx)
        logger.info("Updated invoice %s org=%s", invoice_number, self._ctx.org_id)
        return doc

    async def send_invoice(self, invoice_number: str) -> InvoiceDoc:
        """Mark an invoice as sent (transitions draft → sent)."""
        doc = await InvoiceDoc.find_by_number(self._ctx, invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        current_status = doc.status
        if current_status not in (InvoiceStatus.DRAFT,):
            bad_request(
                message=f"Cannot send invoice with status '{current_status}'. "
                        f"Only draft invoices can be sent."
            )

        doc.status = InvoiceStatus.SENT
        await doc.org_save(self._ctx)
        logger.info("Sent invoice %s org=%s", invoice_number, self._ctx.org_id)
        return doc

    async def void_invoice(self, invoice_number: str) -> InvoiceDoc:
        """Void/cancel an invoice. Cannot void if fully paid."""
        doc = await InvoiceDoc.find_by_number(self._ctx, invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        if doc.status == InvoiceStatus.PAID:
            bad_request(
                message="Cannot void a fully paid invoice. "
                        "Issue a credit note instead."
            )

        doc.status = InvoiceStatus.VOID
        await doc.org_save(self._ctx)
        logger.info("Voided invoice %s org=%s", invoice_number, self._ctx.org_id)
        return doc

    async def apply_payment(
        self,
        invoice_number: str,
        payment_amount: float,
    ) -> InvoiceDoc:
        """
        Update invoice after a payment is recorded.

        Called by PaymentService — not directly by routes.
        Updates amount_paid, balance_due, and status.
        """
        doc = await InvoiceDoc.find_by_number(self._ctx, invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        current_paid = doc.amount_paid
        total = doc.total

        new_paid = round(current_paid + payment_amount, 2)
        new_balance = round(total - new_paid, 2)

        # Derive status from balance
        if new_balance <= 0:
            new_status = InvoiceStatus.PAID
            new_balance = 0.0
        elif new_paid > 0:
            new_status = InvoiceStatus.PARTIAL
        else:
            new_status = doc.status

        doc.amount_paid = new_paid
        doc.balance_due = new_balance
        doc.status = new_status

        await doc.org_save(self._ctx)

        logger.info(
            "Applied payment %.2f to invoice %s → status=%s balance=%.2f",
            payment_amount, invoice_number, new_status, new_balance,
        )
        return doc
