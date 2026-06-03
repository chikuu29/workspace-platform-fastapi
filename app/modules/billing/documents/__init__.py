# billing.documents — Beanie ODM document models for billing.
#
# All billing entities are Beanie documents extending BillingDocument,
# which provides automatic org-scoping, audit trails, and soft-delete.

from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)
from app.modules.billing.documents.credit_note_doc import CreditNoteDoc
from app.modules.billing.documents.gateway_config_doc import (
    CommissionConfigEmbed,
    GatewayConfigDoc,
    OwnerCredentialsEmbed,
)
from app.modules.billing.documents.invoice_doc import (
    InvoiceDoc,
    LineItemEmbed,
    TaxBreakdownEmbed,
)
from app.modules.billing.documents.payment_doc import PaymentDoc
from app.modules.billing.documents.reminder_doc import ReminderDoc
from app.modules.billing.documents.settlement_doc import SettlementDoc
from app.modules.billing.documents.subscription_doc import SubscriptionDoc
from app.modules.billing.documents.tax_profile_doc import TaxProfileDoc

__all__ = [
    # Base
    "BillingDocument",
    "CustomerRefEmbed",
    # Invoice
    "InvoiceDoc",
    "LineItemEmbed",
    "TaxBreakdownEmbed",
    # Payment
    "PaymentDoc",
    # Subscription
    "SubscriptionDoc",
    # Credit Note
    "CreditNoteDoc",
    # Tax Profile
    "TaxProfileDoc",
    # Reminder
    "ReminderDoc",
    # Gateway Config
    "GatewayConfigDoc",
    "CommissionConfigEmbed",
    "OwnerCredentialsEmbed",
    # Settlement
    "SettlementDoc",
]
