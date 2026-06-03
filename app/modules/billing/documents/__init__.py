# billing.documents — Beanie ODM document models for billing.
#
# All billing entities are Beanie documents extending BillingDocument,
# which provides automatic org-scoping, audit trails, and soft-delete.
#
# Collections: orders, invoices, payments, credit_notes, receipts, tax_profiles.

from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)
from app.modules.billing.documents.order_doc import (
    OrderDoc,
    SourceRefEmbed,
)
from app.modules.billing.documents.invoice_doc import (
    InvoiceDoc,
    LineItemEmbed,
    TaxBreakdownEmbed,
)
from app.modules.billing.documents.payment_doc import PaymentDoc
from app.modules.billing.documents.credit_note_doc import CreditNoteDoc
from app.modules.billing.documents.receipt_doc import ReceiptDoc
from app.modules.billing.documents.tax_profile_doc import TaxProfileDoc

__all__ = [
    # Base
    "BillingDocument",
    "CustomerRefEmbed",
    # Order
    "OrderDoc",
    "SourceRefEmbed",
    # Invoice
    "InvoiceDoc",
    "LineItemEmbed",
    "TaxBreakdownEmbed",
    # Payment
    "PaymentDoc",
    # Credit Note
    "CreditNoteDoc",
    # Receipt
    "ReceiptDoc",
    # Tax Profile
    "TaxProfileDoc",
]
