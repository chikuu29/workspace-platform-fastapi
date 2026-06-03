"""
Payment Service — records payments against invoices.

Handles manual payment capture (cash, UPI, card, bank transfer)
and updates the linked invoice's balance via InvoiceService.

When an invoice is fully paid, auto-generates a receipt via ReceiptService.
When the invoice has a linked order, updates order status to COMPLETED.

Future: gateway-mediated payments (Razorpay, Stripe, Cashfree)
will be added here without changing the public interface.

Inherits from BaseBillingService for shared infrastructure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, not_found
from app.core.context import OrgContext
from app.modules.billing.constants import (
    DEFAULT_CURRENCY,
    ENTITY_PAYMENT,
    ENTITY_RECEIPT,
    InvoiceStatus,
    OrderStatus,
    PaymentStatus,
)
from app.modules.billing.documents.invoice_doc import InvoiceDoc
from app.modules.billing.documents.order_doc import OrderDoc
from app.modules.billing.documents.payment_doc import PaymentDoc
from app.modules.billing.schemas.payment_schemas import RecordPaymentInput
from app.modules.billing.services.base import BaseBillingService


class PaymentService(BaseBillingService):
    """
    Payment recording and management.

    Records manual payments against invoices and automatically
    updates the invoice status. When fully paid, triggers
    receipt generation and order completion.

    Public methods:
        record(input_data)         — record a payment against an invoice
        get(payment_number)        — get a single payment
        list(...)                  — list payments with filters
        list_for_invoice(inv_ref)  — get all payments for an invoice
    """

    # ── BaseBillingService Abstract Properties ───────────────────

    @property
    def service_name(self) -> str:
        return "payments"

    @property
    def entity_type(self) -> str:
        return ENTITY_PAYMENT

    @property
    def number_prefix(self) -> str:
        return "PAY"

    # ── Public Methods ───────────────────────────────────────────

    async def record(self, input_data: RecordPaymentInput) -> PaymentDoc:
        """
        Record a payment against an invoice.

        Validates:
        - Invoice exists and is not VOID or DRAFT
        - Payment amount does not exceed balance_due

        Side effects:
        - Updates invoice balance_due and status via InvoiceService
        - If fully paid: auto-generates receipt + updates linked order
        """
        invoice_ref = input_data.invoice_ref
        amount = input_data.amount

        # Validate invoice exists
        invoice_doc = await InvoiceDoc.find_by_number(self._ctx, invoice_ref)
        if not invoice_doc:
            not_found(message=f"Invoice '{invoice_ref}' not found.")

        # Validate invoice status — cannot pay a void or draft invoice
        if invoice_doc.status in (InvoiceStatus.VOID, InvoiceStatus.CANCELLED):
            bad_request(message=f"Cannot pay a {invoice_doc.status} invoice.")

        if invoice_doc.status == InvoiceStatus.DRAFT:
            bad_request(
                message="Cannot pay a draft invoice. Send it first."
            )

        # Validate amount — cannot overpay
        if amount > invoice_doc.balance_due:
            bad_request(
                message=f"Payment amount {amount} exceeds balance_due "
                        f"{invoice_doc.balance_due}."
            )

        # Generate payment number via inherited _generate_number()
        payment_number = await self._generate_number()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Create payment document
        doc = PaymentDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_PAYMENT,
            record_id=payment_number,
            payment_number=payment_number,
            invoice_ref=invoice_ref,
            amount=amount,
            currency=input_data.currency or DEFAULT_CURRENCY,
            method=input_data.method,
            status=PaymentStatus.CAPTURED,
            payment_date=now_str,
            transaction_ref=input_data.transaction_ref or "",
            gateway_payment_id="",
            gateway_order_id="",
            notes=input_data.notes or "",
            source_app=self._ctx.app_code,
        )

        await doc.insert()

        # Apply payment to invoice — updates balance and status
        from app.modules.billing.services.invoice_service import InvoiceService

        invoice_svc = InvoiceService(self._db, self._ctx)
        updated_invoice = await invoice_svc.apply_payment(invoice_ref, amount)

        # If invoice is fully paid → auto-generate receipt + complete order
        if updated_invoice.status == InvoiceStatus.PAID:
            await self._handle_full_payment(updated_invoice, doc)

        self._logger.info(
            "Recorded payment %s amount=%.2f invoice=%s status=%s org=%s",
            payment_number, amount, invoice_ref,
            updated_invoice.status, self._ctx.org_id,
        )
        return doc

    async def get(self, payment_number: str) -> PaymentDoc:
        """Get a single payment by its number."""
        doc = await PaymentDoc.find_by_number(self._ctx, payment_number)
        if not doc:
            not_found(message=f"Payment '{payment_number}' not found.")
        return doc

    async def list(
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

    async def list_for_invoice(
        self, invoice_ref: str,
    ) -> List[PaymentDoc]:
        """Get all payments for a specific invoice."""
        return await PaymentDoc.find_by_invoice(self._ctx, invoice_ref)

    # ── Internal ─────────────────────────────────────────────────

    async def _handle_full_payment(
        self,
        invoice: InvoiceDoc,
        final_payment: PaymentDoc,
    ) -> None:
        """
        Handle side effects when an invoice is fully paid.

        1. Auto-generate a receipt (via ReceiptService)
        2. Update linked order status to COMPLETED (if order exists)
        """
        # 1. Auto-generate receipt
        try:
            from app.modules.billing.services.receipt_service import (
                ReceiptService,
            )

            receipt_svc = ReceiptService(self._db, self._ctx)
            all_payments = await self.list_for_invoice(
                invoice.invoice_number,
            )
            await receipt_svc._generate_receipt(invoice, all_payments)

            self._logger.info(
                "Auto-generated receipt for invoice %s",
                invoice.invoice_number,
            )
        except Exception:
            # Receipt generation failure should not block payment recording
            self._logger.exception(
                "Failed to auto-generate receipt for invoice %s",
                invoice.invoice_number,
            )

        # 2. Update linked order to COMPLETED (if exists)
        try:
            order = await OrderDoc.find_by_invoice(
                self._ctx, invoice.invoice_number,
            )
            if order and order.status != OrderStatus.COMPLETED:
                order.status = OrderStatus.COMPLETED
                await order.org_save(self._ctx)
                self._logger.info(
                    "Order %s completed (invoice %s fully paid)",
                    order.order_number, invoice.invoice_number,
                )
        except Exception:
            self._logger.exception(
                "Failed to update order status for invoice %s",
                invoice.invoice_number,
            )
