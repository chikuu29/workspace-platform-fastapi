"""
Payment Service — records payments and updates invoices using Beanie.

Phase 1: Cash-only payments (no gateway integration).
Phase 2 will add gateway-mediated payments with commission tracking.

Supports all manual payment methods: cash, UPI, card, bank transfer, etc.
Automatically updates invoice status after payment is recorded.
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
    ENTITY_PAYMENT,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.billing_management.documents.invoice_doc import InvoiceDoc
from app.modules.billing_management.documents.payment_doc import PaymentDoc
from app.modules.billing_management.schemas.payment_schemas import RecordPaymentInput
from app.modules.billing_management.services.invoice_service import InvoiceService

logger = create_logger("billing.payment_service")


class PaymentService:
    """Business logic for payment recording and tracking."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx
        self._invoice_svc = InvoiceService(db, ctx)

    async def _generate_payment_number(self) -> str:
        """Generate unique payment number: PAY/2026-27/0001."""
        from app.modules.billing_management.services.invoice_service import (
            _indian_financial_year,
        )
        fy = _indian_financial_year()
        seq = OrgSequenceService(self._db, self._ctx)
        counter_id = f"billing_payment:{fy}"
        doc = await seq._sequences.find_one_and_update(
            {"_id": f"{self._ctx.org_name}:{self._ctx.app_code}:{counter_id}"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        return f"PAY/{fy}/{doc['seq']:04d}"

    async def record_payment(self, input_data: RecordPaymentInput) -> PaymentDoc:
        """
        Record a payment against an invoice.
        Accepts RecordPaymentInput and returns PaymentDoc.
        """
        invoice_ref = input_data.invoice_ref.strip()
        amount = input_data.amount
        method = input_data.method

        # Verify invoice exists and has balance
        invoice_doc = await InvoiceDoc.find_by_number(self._ctx, invoice_ref)
        if not invoice_doc:
            not_found(message=f"Invoice '{invoice_ref}' not found.")

        balance_due = invoice_doc.balance_due
        if balance_due <= 0:
            bad_request(message="This invoice has already been fully paid.")

        # Cap payment at balance due (no overpayment)
        if amount > balance_due:
            amount = balance_due

        # Generate payment number
        payment_number = await self._generate_payment_number()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payment_date_str = input_data.payment_date if input_data.payment_date else now_str

        # Build Beanie document
        doc = PaymentDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_PAYMENT,
            record_id=payment_number,
            payment_number=payment_number,
            invoice_ref=invoice_ref,
            amount=round(amount, 2),
            currency=input_data.currency,
            method=method,
            gateway_tier="",
            gateway_provider="",
            gateway_payment_id="",
            gateway_order_id="",
            gateway_signature="",
            commission_rate=0.0,
            commission_amount=0.0,
            net_to_owner=round(amount, 2),
            status=PaymentStatus.CAPTURED,
            payment_date=payment_date_str,
            transaction_ref=input_data.transaction_ref or "",
            notes=input_data.notes or "",
        )

        # Insert payment record
        await doc.insert()

        # Update invoice (amount_paid, balance_due, status)
        await self._invoice_svc.apply_payment(invoice_ref, amount)

        logger.info(
            "Recorded payment %s amount=%.2f method=%s invoice=%s org=%s",
            payment_number, amount, method, invoice_ref, self._ctx.org_id,
        )

        return doc

    async def list_payments(
        self,
        *,
        invoice_ref: Optional[str] = None,
        method: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[PaymentDoc], int]:
        """List payments with optional filters."""
        query: Dict[str, Any] = {}
        if invoice_ref:
            query["invoice_ref"] = invoice_ref
        if method:
            query["method"] = method
        if status:
            query["status"] = status

        documents = await PaymentDoc.org_find(
            self._ctx,
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await PaymentDoc.org_count(self._ctx, query)
        return documents, total

    async def get_payment(self, payment_number: str) -> PaymentDoc:
        """Get a single payment by number."""
        doc = await PaymentDoc.find_by_number(self._ctx, payment_number)
        if not doc:
            not_found(message=f"Payment '{payment_number}' not found.")
        return doc

    async def list_payments_for_invoice(self, invoice_ref: str) -> List[PaymentDoc]:
        """List payments for a specific invoice."""
        return await PaymentDoc.find_by_invoice(self._ctx, invoice_ref)
