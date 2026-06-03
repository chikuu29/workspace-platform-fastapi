"""
BillingService — unified billing SDK facade.

The single entry point for all billing operations. Domain apps
instantiate this once per request and access capabilities through
descriptive property names.

Usage:
    from app.modules.billing import BillingService

    billing = BillingService(db, ctx)

    order = await billing.orders.create(input_data)
    order, invoice = await billing.orders.confirm(order.order_number)
    invoice = await billing.invoices.send(invoice.invoice_number)
    payment = await billing.payments.record(payment_input)
    receipt = await billing.receipts.get_for_invoice(invoice.invoice_number)
    cn = await billing.credit_notes.issue(cn_input)
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.context import OrgContext
from app.modules.billing.services.credit_note_service import (
    CreditNoteService,
)
from app.modules.billing.services.invoice_service import InvoiceService
from app.modules.billing.services.order_service import OrderService
from app.modules.billing.services.payment_service import PaymentService
from app.modules.billing.services.receipt_service import ReceiptService
from app.modules.billing.services.tax_profile_service import (
    TaxProfileService,
)


class BillingService:
    """
    Unified billing SDK — the single entry point for all billing operations.

    Composes sub-services into a clean, discoverable interface.
    Sub-services are lazy-initialized on first access to avoid
    overhead when only a subset of operations is needed.

    Properties:
        orders       — Order lifecycle: create, confirm, cancel, get, list
        invoices     — Invoice lifecycle: create, send, void, list, get
        payments     — Payment recording: record, list, get
        credit_notes — Refund & credit notes: issue, apply, void, list, get
        receipts     — Receipts: get, list (read-only, auto-generated)
        tax_profiles — Tax profile management: create, update, list, preview
    """

    __slots__ = (
        "_db",
        "_ctx",
        "_orders",
        "_invoices",
        "_payments",
        "_credit_notes",
        "_receipts",
        "_tax_profiles",
    )

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        """
        Initialize the billing SDK.

        Args:
            db: Motor async database instance.
            ctx: Current request's org context (from JWT + headers).
        """
        self._db = db
        self._ctx = ctx
        # Lazy-init sub-services on first access
        self._orders: OrderService | None = None
        self._invoices: InvoiceService | None = None
        self._payments: PaymentService | None = None
        self._credit_notes: CreditNoteService | None = None
        self._receipts: ReceiptService | None = None
        self._tax_profiles: TaxProfileService | None = None

    @property
    def orders(self) -> OrderService:
        """Order lifecycle: create, confirm, cancel, get, list."""
        if self._orders is None:
            self._orders = OrderService(self._db, self._ctx)
        return self._orders

    @property
    def invoices(self) -> InvoiceService:
        """Invoice lifecycle: create, send, void, list, get."""
        if self._invoices is None:
            self._invoices = InvoiceService(self._db, self._ctx)
        return self._invoices

    @property
    def payments(self) -> PaymentService:
        """Payment recording: record, list, get."""
        if self._payments is None:
            self._payments = PaymentService(self._db, self._ctx)
        return self._payments

    @property
    def credit_notes(self) -> CreditNoteService:
        """Refund & credit notes: issue, apply, void, list, get."""
        if self._credit_notes is None:
            self._credit_notes = CreditNoteService(self._db, self._ctx)
        return self._credit_notes

    @property
    def receipts(self) -> ReceiptService:
        """Receipts: get, list (read-only — auto-generated on full payment)."""
        if self._receipts is None:
            self._receipts = ReceiptService(self._db, self._ctx)
        return self._receipts

    @property
    def tax_profiles(self) -> TaxProfileService:
        """Tax profile management: create, update, list, preview."""
        if self._tax_profiles is None:
            self._tax_profiles = TaxProfileService(self._db, self._ctx)
        return self._tax_profiles
