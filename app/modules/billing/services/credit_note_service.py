"""
Credit Note Service — refund and credit note lifecycle.

Handles partial and full refunds against invoices.
Issues credit notes, applies them to reduce invoice balance,
and supports voiding.

Status lifecycle: draft → issued → applied → (void)

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
    ENTITY_CREDIT_NOTE,
    CreditNoteStatus,
    InvoiceStatus,
)
from app.modules.billing.documents.credit_note_doc import CreditNoteDoc
from app.modules.billing.documents.invoice_doc import InvoiceDoc
from app.modules.billing.schemas.credit_note_schemas import (
    IssueCreditNoteInput,
)
from app.modules.billing.services.base import BaseBillingService


class CreditNoteService(BaseBillingService):
    """
    Credit note & refund lifecycle management.

    Handles partial and full refunds against invoices.
    Issues credit notes, applies them to reduce invoice balance,
    and supports voiding before application.

    Public methods:
        issue(input_data)            — issue a credit note against an invoice
        apply(credit_note_number)    — apply credit note → adjusts invoice balance
        void(credit_note_number)     — void a draft or issued credit note
        get(credit_note_number)      — get a single credit note
        list(...)                    — list credit notes with filters
    """

    # ── BaseBillingService Abstract Properties ───────────────────

    @property
    def service_name(self) -> str:
        return "credit_notes"

    @property
    def entity_type(self) -> str:
        return ENTITY_CREDIT_NOTE

    @property
    def number_prefix(self) -> str:
        return "CN"

    # ── Public Methods ───────────────────────────────────────────

    async def issue(
        self, input_data: IssueCreditNoteInput,
    ) -> CreditNoteDoc:
        """
        Issue a credit note against an invoice.

        Validates:
        - Source invoice exists and is not DRAFT or VOID
        - Refund amount does not exceed invoice total minus existing credits

        Generates: sequential number CN/{FY}/{counter}.
        """
        invoice_ref = input_data.invoice_ref
        refund_amount = input_data.refund_amount

        # Validate source invoice
        invoice_doc = await InvoiceDoc.find_by_number(self._ctx, invoice_ref)
        if not invoice_doc:
            not_found(message=f"Invoice '{invoice_ref}' not found.")

        if invoice_doc.status in (
            InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED,
        ):
            bad_request(
                message=f"Cannot issue credit note against a "
                        f"{invoice_doc.status} invoice.",
            )

        # Validate refund amount — sum of existing credit notes + this amount
        # must not exceed invoice total
        existing_cns, _ = await self.list(invoice_ref=invoice_ref)
        existing_credit_total = sum(
            cn.total for cn in existing_cns
            if cn.status != CreditNoteStatus.VOID
        )

        max_refundable = round(invoice_doc.total - existing_credit_total, 2)
        if refund_amount > max_refundable:
            bad_request(
                message=f"Refund amount {refund_amount} exceeds maximum "
                        f"refundable amount {max_refundable}.",
            )

        # Generate credit note number
        cn_number = await self._generate_number()

        # Compute proportional tax reversal
        # Tax ratio = original tax / original subtotal
        tax_ratio = (
            invoice_doc.tax_breakdown.total_tax / invoice_doc.subtotal
            if invoice_doc.subtotal > 0
            else 0.0
        )
        tax_reversal = round(refund_amount * tax_ratio / (1 + tax_ratio), 2)
        subtotal_refund = round(refund_amount - tax_reversal, 2)

        # Build credit note line items from input (if provided)
        cn_line_items = []
        if input_data.line_items:
            for item in input_data.line_items:
                cn_line_items.append({
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "tax_category": item.tax_category,
                    "source_item_code": item.source_item_code,
                })

        # Create credit note document
        doc = CreditNoteDoc.create_for_org(
            self._ctx,
            entity_type=ENTITY_CREDIT_NOTE,
            record_id=cn_number,
            credit_note_number=cn_number,
            invoice_ref=invoice_ref,
            reason=input_data.reason,
            line_items=cn_line_items,
            subtotal=subtotal_refund,
            tax_amount=tax_reversal,
            total=refund_amount,
            currency=invoice_doc.currency or DEFAULT_CURRENCY,
            status=CreditNoteStatus.ISSUED,
            issue_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            notes=input_data.notes or "",
            source_app=self._ctx.app_code,
        )

        await doc.insert()

        self._logger.info(
            "Issued credit note %s amount=%.2f against invoice %s org=%s",
            cn_number, refund_amount, invoice_ref, self._ctx.org_id,
        )
        return doc

    async def apply(self, credit_note_number: str) -> CreditNoteDoc:
        """
        Apply a credit note — adjusts the linked invoice's balance.

        Transitions: issued → applied
        Side effect: reduces invoice.balance_due and increases amount_paid.
        """
        doc = await CreditNoteDoc.find_by_number(self._ctx, credit_note_number)
        if not doc:
            not_found(
                message=f"Credit note '{credit_note_number}' not found.",
            )

        if doc.status != CreditNoteStatus.ISSUED:
            bad_request(
                message=f"Cannot apply credit note with status '{doc.status}'. "
                        f"Only issued credit notes can be applied.",
            )

        # Adjust linked invoice balance
        invoice_doc = await InvoiceDoc.find_by_number(
            self._ctx, doc.invoice_ref,
        )
        if not invoice_doc:
            not_found(message=f"Linked invoice '{doc.invoice_ref}' not found.")

        # Reduce balance_due by credit note total
        new_paid = round(invoice_doc.amount_paid + doc.total, 2)
        new_balance = round(invoice_doc.total - new_paid, 2)

        if new_balance <= 0:
            invoice_doc.status = InvoiceStatus.PAID
            new_balance = 0.0
        elif new_paid > 0:
            invoice_doc.status = InvoiceStatus.PARTIAL

        invoice_doc.amount_paid = new_paid
        invoice_doc.balance_due = new_balance
        await invoice_doc.org_save(self._ctx)

        # Update credit note status
        doc.status = CreditNoteStatus.APPLIED
        await doc.org_save(self._ctx)

        self._logger.info(
            "Applied credit note %s to invoice %s new_balance=%.2f org=%s",
            credit_note_number, doc.invoice_ref, new_balance, self._ctx.org_id,
        )
        return doc

    async def void(self, credit_note_number: str) -> CreditNoteDoc:
        """
        Void a credit note.

        Only draft or issued credit notes can be voided.
        Applied credit notes cannot be voided — the balance
        adjustment has already been applied to the invoice.
        """
        doc = await CreditNoteDoc.find_by_number(self._ctx, credit_note_number)
        if not doc:
            not_found(
                message=f"Credit note '{credit_note_number}' not found.",
            )

        if doc.status == CreditNoteStatus.APPLIED:
            bad_request(
                message="Cannot void an applied credit note. "
                        "The balance adjustment has already been applied.",
            )

        if doc.status == CreditNoteStatus.VOID:
            bad_request(message="Credit note is already void.")

        doc.status = CreditNoteStatus.VOID
        await doc.org_save(self._ctx)

        self._logger.info(
            "Voided credit note %s org=%s",
            credit_note_number, self._ctx.org_id,
        )
        return doc

    async def get(self, credit_note_number: str) -> CreditNoteDoc:
        """Get a single credit note by its number."""
        doc = await CreditNoteDoc.find_by_number(self._ctx, credit_note_number)
        if not doc:
            not_found(
                message=f"Credit note '{credit_note_number}' not found.",
            )
        return doc

    async def list(
        self,
        *,
        invoice_ref: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[CreditNoteDoc], int]:
        """List credit notes with optional filters."""
        query: Dict[str, Any] = {}
        if invoice_ref:
            query["invoice_ref"] = invoice_ref
        if status:
            query["status"] = status

        documents = await CreditNoteDoc.org_find(
            self._ctx,
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )
        total = await CreditNoteDoc.org_count(self._ctx, query)
        return documents, total
