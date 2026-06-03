"""
billing — Centralized, app-agnostic billing engine.

SDK Usage:
    from app.modules.billing import (
        BillingService,
        CreateOrderInput,
        CreateInvoiceInput,
        RecordPaymentInput,
        IssueCreditNoteInput,
        ServiceLineItem,
        CustomerRefSchema,
    )

    billing = BillingService(db, ctx)

    order = await billing.orders.create(order_input)
    order, invoice = await billing.orders.confirm(order.order_number)
    payment = await billing.payments.record(payment_input)
    receipt = await billing.receipts.get_for_invoice(invoice.invoice_number)
"""

from app.modules.billing.service import BillingService

# ── Typed Contracts (input schemas for domain apps) ──────────────
from app.modules.billing.schemas.common import CustomerRefSchema
from app.modules.billing.schemas.order_schemas import CreateOrderInput
from app.modules.billing.schemas.invoice_schemas import (
    CreateInvoiceInput,
    UpdateInvoiceInput,
)
from app.modules.billing.schemas.payment_schemas import RecordPaymentInput
from app.modules.billing.schemas.credit_note_schemas import (
    IssueCreditNoteInput,
)
from app.modules.billing.schemas.line_items import (
    GoodsLineItem,
    ServiceLineItem,
    SubscriptionLineItem,
    LineItemInput,
)

__all__ = [
    # SDK Entry Point
    "BillingService",
    # Order
    "CreateOrderInput",
    # Invoice
    "CreateInvoiceInput",
    "UpdateInvoiceInput",
    # Payment
    "RecordPaymentInput",
    # Credit Note
    "IssueCreditNoteInput",
    # Line Items
    "GoodsLineItem",
    "ServiceLineItem",
    "SubscriptionLineItem",
    "LineItemInput",
    # Common
    "CustomerRefSchema",
]
