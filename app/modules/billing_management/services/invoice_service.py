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
    compute_invoice_totals,
)
from app.modules.billing_management.engines.tax_engine import (
    compute_line_tax,
    compute_invoice_tax,
)
from app.modules.billing_management.models.base import TaxBreakdown
from app.modules.billing_management.repositories.billing_repos import (
    InvoiceRepository,
    PaymentRepository,
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
    """Business logic for the invoice lifecycle."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx
        self._invoice_repo = InvoiceRepository(db, ctx)
        self._payment_repo = PaymentRepository(db, ctx)

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
        return f"INV/{fy}/{doc['seq']:04d}"

    async def create_invoice(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create an invoice with full tax + pricing computation.

        Expected payload:
        {
            "customer_ref": { "ref_type": "member", "ref_id": "M-1", "name": "John", ... },
            "seller_gstin": "29AABCU9603R1ZM",
            "buyer_gstin": "27AADCB2230M1Z3",      // optional (B2B)
            "place_of_supply": "27",                 // state code
            "line_items": [
                {
                    "catalog_item_code": "GYM_PRO",  // optional — can be freeform
                    "description": "Pro Gym Plan",
                    "quantity": 1,
                    "unit_price": 5000,
                    "tax_category": "higher",         // GST category
                    "hsn_sac_code": "997212",
                    "discount_type": "percentage",    // optional
                    "discount_value": 10              // optional
                }
            ],
            "due_date": "2026-06-15",
            "notes": "First month free promo"
        }
        """
        # ── Validate required fields ──────────────────────────────────
        customer_ref = data.get("customer_ref")
        if not customer_ref or not customer_ref.get("ref_id"):
            bad_request(message="customer_ref with ref_id is required.")

        raw_items = data.get("line_items", [])
        if not raw_items:
            bad_request(message="At least one line_item is required.")

        seller_gstin = data.get("seller_gstin", "")
        buyer_gstin = data.get("buyer_gstin", "")
        place_of_supply = data.get("place_of_supply", "")

        # ── Process each line item ────────────────────────────────────
        computed_items: List[Dict[str, Any]] = []
        line_tax_inputs: list[tuple[float, str]] = []

        for item in raw_items:
            qty = float(item.get("quantity", 1))
            price = float(item.get("unit_price", 0))
            disc_type = item.get("discount_type", "none")
            disc_value = float(item.get("discount_value", 0))
            tax_cat = item.get("tax_category", "higher")

            # Pricing: qty × price − discount
            line_calc = compute_line_pricing(
                quantity=qty,
                unit_price=price,
                discount_type=disc_type,
                discount_value=disc_value,
                tax_amount=0.0,  # Will compute tax separately
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

            computed_items.append({
                "catalog_item_code": item.get("catalog_item_code", ""),
                "description": item.get("description", ""),
                "hsn_sac_code": item.get("hsn_sac_code", ""),
                "quantity": qty,
                "unit_price": price,
                "discount_type": disc_type,
                "discount_value": disc_value,
                "discount_amount": final_calc.discount_amount,
                "tax_category": tax_cat,
                "tax_rate": line_tax.tax_rate,
                "tax_amount": line_tax.total_tax,
                "taxable_amount": final_calc.taxable_amount,
                "line_total": final_calc.line_total,
            })

            line_tax_inputs.append((final_calc.taxable_amount, tax_cat))

        # ── Aggregate invoice totals ──────────────────────────────────
        agg_tax = compute_invoice_tax(
            line_taxable_amounts=line_tax_inputs,
            seller_gstin=seller_gstin,
            place_of_supply=place_of_supply or buyer_gstin,
        )

        subtotal = sum(li["taxable_amount"] for li in computed_items)
        total = round(subtotal + agg_tax.total_tax, 2)

        # ── Generate invoice number ───────────────────────────────────
        invoice_number = await self._generate_invoice_number()

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        invoice_data: Dict[str, Any] = {
            "invoice_number": invoice_number,
            "invoice_type": data.get("invoice_type", "standard"),
            "customer_ref": customer_ref,
            "line_items": computed_items,
            "subtotal": round(subtotal, 2),
            "tax_breakdown": agg_tax.to_dict(),
            "total": total,
            "amount_paid": 0.0,
            "balance_due": total,
            "currency": data.get("currency", DEFAULT_CURRENCY),
            "seller_gstin": seller_gstin,
            "buyer_gstin": buyer_gstin,
            "place_of_supply": place_of_supply,
            "is_inter_state": agg_tax.is_inter_state,
            "status": InvoiceStatus.DRAFT,
            "issue_date": now_str,
            "due_date": data.get("due_date", now_str),
            "payment_terms": data.get("payment_terms", DEFAULT_PAYMENT_TERMS),
            "source_app": self._ctx.app_code,
            "notes": data.get("notes", ""),
            "terms_and_conditions": data.get("terms_and_conditions", ""),
        }

        document = await self._invoice_repo.insert_one(
            data=invoice_data,
            entity_type=ENTITY_INVOICE,
            prefix="INV",
        )

        logger.info(
            "Created invoice %s total=%.2f org=%s app=%s",
            invoice_number, total, self._ctx.org_id, self._ctx.app_code,
        )
        return document

    async def list_invoices(
        self,
        *,
        status: Optional[str] = None,
        customer_ref_id: Optional[str] = None,
        source_app: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List invoices with optional filters."""
        query: Dict[str, Any] = {}
        if status:
            query["data.status"] = status
        if customer_ref_id:
            query["data.customer_ref.ref_id"] = customer_ref_id
        if source_app:
            query["data.source_app"] = source_app

        documents = await self._invoice_repo.find(
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await self._invoice_repo.count(query)
        return documents, total

    async def get_invoice(self, invoice_number: str) -> Dict[str, Any]:
        """Get a single invoice with payment history."""
        doc = await self._invoice_repo.find_by_number(invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        # Attach payment history
        payments = await self._payment_repo.find_by_invoice(invoice_number)
        doc["payment_history"] = payments
        return doc

    async def update_invoice(
        self, invoice_number: str, update_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Update an invoice. Only draft invoices can be edited.

        For status changes, use send_invoice() or void_invoice() instead.
        """
        doc = await self._invoice_repo.find_by_number(invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        if doc["data"]["status"] != InvoiceStatus.DRAFT:
            bad_request(
                message="Only draft invoices can be edited. "
                        f"Current status: {doc['data']['status']}."
            )

        updated = await self._invoice_repo.update_one(
            {"data.invoice_number": invoice_number},
            update_data,
        )
        if not updated:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        logger.info("Updated invoice %s org=%s", invoice_number, self._ctx.org_id)
        return updated

    async def send_invoice(self, invoice_number: str) -> Dict[str, Any]:
        """Mark an invoice as sent (transitions draft → sent)."""
        doc = await self._invoice_repo.find_by_number(invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        current_status = doc["data"]["status"]
        if current_status not in (InvoiceStatus.DRAFT,):
            bad_request(
                message=f"Cannot send invoice with status '{current_status}'. "
                        f"Only draft invoices can be sent."
            )

        updated = await self._invoice_repo.update_one(
            {"data.invoice_number": invoice_number},
            {"status": InvoiceStatus.SENT},
        )
        logger.info("Sent invoice %s org=%s", invoice_number, self._ctx.org_id)
        return updated

    async def void_invoice(self, invoice_number: str) -> Dict[str, Any]:
        """Void/cancel an invoice. Cannot void if fully paid."""
        doc = await self._invoice_repo.find_by_number(invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        if doc["data"]["status"] == InvoiceStatus.PAID:
            bad_request(
                message="Cannot void a fully paid invoice. "
                        "Issue a credit note instead."
            )

        updated = await self._invoice_repo.update_one(
            {"data.invoice_number": invoice_number},
            {"status": InvoiceStatus.VOID},
        )
        logger.info("Voided invoice %s org=%s", invoice_number, self._ctx.org_id)
        return updated

    async def apply_payment(
        self,
        invoice_number: str,
        payment_amount: float,
    ) -> Dict[str, Any]:
        """
        Update invoice after a payment is recorded.

        Called by PaymentService — not directly by routes.
        Updates amount_paid, balance_due, and status.
        """
        doc = await self._invoice_repo.find_by_number(invoice_number)
        if not doc:
            not_found(message=f"Invoice '{invoice_number}' not found.")

        current_paid = float(doc["data"].get("amount_paid", 0.0))
        total = float(doc["data"].get("total", 0.0))

        new_paid = round(current_paid + payment_amount, 2)
        new_balance = round(total - new_paid, 2)

        # Derive status from balance
        if new_balance <= 0:
            new_status = InvoiceStatus.PAID
            new_balance = 0.0
        elif new_paid > 0:
            new_status = InvoiceStatus.PARTIAL
        else:
            new_status = doc["data"]["status"]

        updated = await self._invoice_repo.update_one(
            {"data.invoice_number": invoice_number},
            {
                "amount_paid": new_paid,
                "balance_due": new_balance,
                "status": new_status,
            },
        )

        logger.info(
            "Applied payment %.2f to invoice %s → status=%s balance=%.2f",
            payment_amount, invoice_number, new_status, new_balance,
        )
        return updated
