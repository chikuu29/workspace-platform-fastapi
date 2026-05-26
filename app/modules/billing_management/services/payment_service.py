"""
Payment Service — records payments and updates invoices.

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
from app.modules.billing_management.repositories.billing_repos import (
    InvoiceRepository,
    PaymentRepository,
)
from app.modules.billing_management.services.invoice_service import InvoiceService

logger = create_logger("billing.payment_service")


class PaymentService:
    """Business logic for payment recording and tracking."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx
        self._payment_repo = PaymentRepository(db, ctx)
        self._invoice_repo = InvoiceRepository(db, ctx)
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

    async def record_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record a payment against an invoice.

        Expected payload:
        {
            "invoice_ref": "INV/2026-27/0001",
            "amount": 5000.00,
            "method": "cash",          // cash, upi, card, bank_transfer, etc.
            "transaction_ref": "",     // Optional: UPI ref, bank txn ID
            "notes": "Cash received at counter"
        }
        """
        invoice_ref = data.get("invoice_ref", "").strip()
        amount = float(data.get("amount", 0))
        method = data.get("method", PaymentMethod.CASH)

        # ── Validation ────────────────────────────────────────────────
        if not invoice_ref:
            bad_request(message="invoice_ref is required.")
        if amount <= 0:
            bad_request(message="Payment amount must be greater than zero.")

        # Verify invoice exists and has balance
        invoice_doc = await self._invoice_repo.find_by_number(invoice_ref)
        if not invoice_doc:
            not_found(message=f"Invoice '{invoice_ref}' not found.")

        balance_due = float(invoice_doc["data"].get("balance_due", 0))
        if balance_due <= 0:
            bad_request(message="This invoice has already been fully paid.")

        # Cap payment at balance due (no overpayment)
        if amount > balance_due:
            amount = balance_due

        # ── Generate payment number ───────────────────────────────────
        payment_number = await self._generate_payment_number()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        payment_data: Dict[str, Any] = {
            "payment_number": payment_number,
            "invoice_ref": invoice_ref,
            "amount": round(amount, 2),
            "currency": data.get("currency", DEFAULT_CURRENCY),
            "method": method,
            "gateway_tier": "",           # Empty for cash/manual
            "gateway_provider": "",
            "gateway_payment_id": "",
            "gateway_order_id": "",
            "gateway_signature": "",
            "commission_rate": 0.0,       # No commission for cash
            "commission_amount": 0.0,
            "net_to_owner": round(amount, 2),
            "status": PaymentStatus.CAPTURED,
            "payment_date": data.get("payment_date", now_str),
            "transaction_ref": data.get("transaction_ref", ""),
            "notes": data.get("notes", ""),
        }

        # ── Insert payment record ─────────────────────────────────────
        payment_doc = await self._payment_repo.insert_one(
            data=payment_data,
            entity_type=ENTITY_PAYMENT,
            prefix="PAY",
        )

        # ── Update invoice (amount_paid, balance_due, status) ─────────
        await self._invoice_svc.apply_payment(invoice_ref, amount)

        logger.info(
            "Recorded payment %s amount=%.2f method=%s invoice=%s org=%s",
            payment_number, amount, method, invoice_ref, self._ctx.org_id,
        )

        return payment_doc

    async def list_payments(
        self,
        *,
        invoice_ref: Optional[str] = None,
        method: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List payments with optional filters."""
        query: Dict[str, Any] = {}
        if invoice_ref:
            query["data.invoice_ref"] = invoice_ref
        if method:
            query["data.method"] = method
        if status:
            query["data.status"] = status

        documents = await self._payment_repo.find(
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await self._payment_repo.count(query)
        return documents, total

    async def get_payment(self, payment_number: str) -> Dict[str, Any]:
        """Get a single payment by number."""
        doc = await self._payment_repo.find_by_number(payment_number)
        if not doc:
            not_found(message=f"Payment '{payment_number}' not found.")
        return doc
