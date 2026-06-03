"""
Billing Constants — centralized enums, entity types, and default values.

All billing modules reference these constants. Using StrEnum ensures
type safety and serialization compatibility with MongoDB / JSON.
"""

from __future__ import annotations

from enum import StrEnum


# ── Entity Types ─────────────────────────────────────────────────────
# Each entity_type maps to a logical document class within billing
# collections. Used in _meta.entity_type for filtering.

ENTITY_CATALOG = "catalog"
ENTITY_INVOICE = "invoice"
ENTITY_PAYMENT = "payment"
ENTITY_SUBSCRIPTION = "subscription"
ENTITY_CREDIT_NOTE = "credit_note"
ENTITY_TAX_PROFILE = "tax_profile"
ENTITY_REMINDER = "reminder"
ENTITY_GATEWAY_CONFIG = "gateway_config"
ENTITY_SETTLEMENT = "settlement"


# ── Collection Names ─────────────────────────────────────────────────
# Separate collections for billing data — not the shared `records` coll.

COLL_CATALOG = "catalog"
COLL_INVOICES = "invoices"
COLL_PAYMENTS = "payments"
COLL_SUBSCRIPTIONS = "subscriptions"
COLL_CREDIT_NOTES = "credit_notes"
COLL_TAX_PROFILES = "tax_profiles"
COLL_REMINDERS = "reminders"
COLL_GATEWAY_CONFIGS = "gateway_configs"
COLL_SETTLEMENTS = "settlements"


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


# ── Gateway ──────────────────────────────────────────────────────────

class GatewayTier(StrEnum):
    """
    Two-tier model:
    - OWNER: Org owner's own Razorpay/Stripe keys → direct payment
    - PLATFORM: Platform's keys → collect, deduct commission, settle
    """
    OWNER = "owner"
    PLATFORM = "platform"


class GatewayProvider(StrEnum):
    RAZORPAY = "razorpay"
    STRIPE = "stripe"
    NONE = "none"


class CommissionRateType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


# ── Settlement ───────────────────────────────────────────────────────

class SettlementStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SettlementMode(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


# ── Subscription ─────────────────────────────────────────────────────

class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PENDING_ACTIVATION = "pending_activation"


# ── Credit Note ──────────────────────────────────────────────────────

class CreditNoteStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    APPLIED = "applied"
    VOID = "void"


# ── Reminder ─────────────────────────────────────────────────────────

class ReminderType(StrEnum):
    UPCOMING = "upcoming"
    OVERDUE = "overdue"
    RECURRING_RENEWAL = "recurring_renewal"


class ReminderChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    IN_APP = "in_app"


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
DEFAULT_COMMISSION_RATE = 5.0  # Platform commission %
DEFAULT_MIN_COMMISSION = 10.0  # ₹10 minimum per transaction
DEFAULT_PAYMENT_LINK_EXPIRY_HOURS = 72
DEFAULT_REMINDER_DAYS_BEFORE = 3
