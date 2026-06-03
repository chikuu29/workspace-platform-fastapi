"""
Billing Constants — centralized enums, entity types, and default values.

All billing modules reference these constants. Using StrEnum ensures
type safety and serialization compatibility with MongoDB / JSON.

Collections kept: orders, invoices, payments, credit_notes, receipts, tax_profiles.
Removed (Phase 2 future): subscriptions, reminders, gateway_configs, settlements.
"""

from __future__ import annotations

from enum import StrEnum


# ── Entity Types ─────────────────────────────────────────────────────
# Each entity_type maps to a logical document class within billing
# collections. Used in _meta.entity_type for filtering.

ENTITY_ORDER = "order"
ENTITY_INVOICE = "invoice"
ENTITY_PAYMENT = "payment"
ENTITY_CREDIT_NOTE = "credit_note"
ENTITY_RECEIPT = "receipt"
ENTITY_TAX_PROFILE = "tax_profile"
ENTITY_CATALOG = "catalog"


# ── Collection Names ─────────────────────────────────────────────────
# Separate collections for billing data — not the shared `records` coll.

COLL_ORDERS = "orders"
COLL_INVOICES = "invoices"
COLL_PAYMENTS = "payments"
COLL_CREDIT_NOTES = "credit_notes"
COLL_RECEIPTS = "receipts"
COLL_TAX_PROFILES = "tax_profiles"
COLL_CATALOG = "catalog"


# ── Order ────────────────────────────────────────────────────────────

class OrderStatus(StrEnum):
    """Billing order lifecycle states."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    INVOICED = "invoiced"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ── Catalog Item Types ───────────────────────────────────────────────

class CatalogItemType(StrEnum):
    """What kind of thing is being sold."""
    PRODUCT = "product"
    SERVICE = "service"
    SUBSCRIPTION_PLAN = "subscription_plan"


# ── Billing Cycle ────────────────────────────────────────────────────

class BillingCycle(StrEnum):
    """Recurrence interval for subscription-based items."""
    ONE_TIME = "one_time"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    YEARLY = "yearly"


# ── Invoice ──────────────────────────────────────────────────────────

class InvoiceType(StrEnum):
    STANDARD = "standard"
    PROFORMA = "proforma"
    CREDIT_NOTE = "credit_note"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    VOID = "void"


# ── Payment ──────────────────────────────────────────────────────────

class PaymentMethod(StrEnum):
    CASH = "cash"
    UPI = "upi"
    CARD = "card"
    NET_BANKING = "net_banking"
    WALLET = "wallet"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    GATEWAY = "gateway"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


# ── Discount ─────────────────────────────────────────────────────────

class DiscountType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    NONE = "none"


# ── Credit Note ──────────────────────────────────────────────────────

class CreditNoteStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    APPLIED = "applied"
    VOID = "void"


# ── Receipt ──────────────────────────────────────────────────────────

class ReceiptStatus(StrEnum):
    ISSUED = "issued"
    VOID = "void"


# ── Tax ──────────────────────────────────────────────────────────────

class TaxType(StrEnum):
    GST = "gst"
    VAT = "vat"
    NONE = "none"


class GSTCategory(StrEnum):
    """Standard GST rate categories in India."""
    EXEMPT = "exempt"         # 0%
    NIL = "nil"               # 0% (different legal treatment)
    LOW = "low"               # 5%
    STANDARD = "standard"     # 12%
    HIGHER = "higher"         # 18%
    LUXURY = "luxury"         # 28%


# ── GST Rate Map (category → percentage) ─────────────────────────────
# These are the standard GST slab rates as of 2026.
# The tax engine uses this map but also supports custom rates per item.

GST_RATE_MAP: dict[GSTCategory, float] = {
    GSTCategory.EXEMPT: 0.0,
    GSTCategory.NIL: 0.0,
    GSTCategory.LOW: 5.0,
    GSTCategory.STANDARD: 12.0,
    GSTCategory.HIGHER: 18.0,
    GSTCategory.LUXURY: 28.0,
}


# ── Defaults ─────────────────────────────────────────────────────────

DEFAULT_CURRENCY = "INR"
DEFAULT_TAX_RATE = 18.0  # GST higher rate (most services)
DEFAULT_PAYMENT_TERMS = "Due on receipt"
