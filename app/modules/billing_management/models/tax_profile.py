"""Subscription, TaxProfile, CreditNote, PaymentReminder — supporting models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.modules.billing_management.constants import (
    BillingCycle,
    CreditNoteStatus,
    DEFAULT_CURRENCY,
    ENTITY_CREDIT_NOTE,
    ENTITY_REMINDER,
    ENTITY_SUBSCRIPTION,
    ENTITY_TAX_PROFILE,
    GSTCategory,
    ReminderChannel,
    ReminderStatus,
    ReminderType,
    SubscriptionStatus,
    TaxType,
)
from app.modules.billing_management.models.base import BillingEntity, CustomerRef


# ── Tax Profile ──────────────────────────────────────────────────────

@dataclass
class TaxProfile(BillingEntity):
    """
    Org-level GST registration and default tax configuration.

    Supports multiple profiles per org (for multi-state GST).
    The GSTIN on invoices is passed via API at creation time,
    but profiles provide default rates and state codes.
    """
    profile_name: str = ""
    gstin: str = ""                    # e.g. "29AABCU9603R1ZM"
    legal_name: str = ""               # Legal entity name
    trade_name: str = ""               # Trade/brand name
    state_code: str = ""               # 2-digit state code (e.g. "29" for Karnataka)
    state_name: str = ""
    tax_type: str = TaxType.GST
    default_tax_category: str = GSTCategory.HIGHER  # Default GST rate category
    is_composition_scheme: bool = False
    is_default: bool = False           # Default profile for this org

    @property
    def entity_type(self) -> str:
        return ENTITY_TAX_PROFILE

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "gstin": self.gstin,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "state_code": self.state_code,
            "state_name": self.state_name,
            "tax_type": self.tax_type,
            "default_tax_category": self.default_tax_category,
            "is_composition_scheme": self.is_composition_scheme,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaxProfile:
        return cls(
            profile_name=data.get("profile_name", ""),
            gstin=data.get("gstin", ""),
            legal_name=data.get("legal_name", ""),
            trade_name=data.get("trade_name", ""),
            state_code=data.get("state_code", ""),
            state_name=data.get("state_name", ""),
            tax_type=data.get("tax_type", TaxType.GST),
            default_tax_category=data.get("default_tax_category", GSTCategory.HIGHER),
            is_composition_scheme=data.get("is_composition_scheme", False),
            is_default=data.get("is_default", False),
        )


# ── Subscription ─────────────────────────────────────────────────────

@dataclass
class Subscription(BillingEntity):
    """
    A recurring subscription instance.

    Links a customer to a catalog plan with billing cycle tracking.
    Auto-generates invoices on renewal if auto_renew is True.
    """
    subscription_number: str = ""
    customer_ref: Optional[CustomerRef] = None
    plan_code: str = ""
    plan_name: str = ""
    billing_cycle: str = BillingCycle.MONTHLY
    unit_price: float = 0.0
    currency: str = DEFAULT_CURRENCY

    status: str = SubscriptionStatus.ACTIVE
    current_period_start: str = ""
    current_period_end: str = ""
    next_billing_date: str = ""
    auto_renew: bool = True
    renewal_count: int = 0

    # Source tracking
    source_app: str = ""

    notes: str = ""

    @property
    def entity_type(self) -> str:
        return ENTITY_SUBSCRIPTION

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "subscription_number": self.subscription_number,
            "customer_ref": self.customer_ref.to_dict() if self.customer_ref else None,
            "plan_code": self.plan_code,
            "plan_name": self.plan_name,
            "billing_cycle": self.billing_cycle,
            "unit_price": self.unit_price,
            "currency": self.currency,
            "status": self.status,
            "current_period_start": self.current_period_start,
            "current_period_end": self.current_period_end,
            "next_billing_date": self.next_billing_date,
            "auto_renew": self.auto_renew,
            "renewal_count": self.renewal_count,
            "source_app": self.source_app,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Subscription:
        cust_data = data.get("customer_ref")
        return cls(
            subscription_number=data.get("subscription_number", ""),
            customer_ref=CustomerRef.from_dict(cust_data) if cust_data else None,
            plan_code=data.get("plan_code", ""),
            plan_name=data.get("plan_name", ""),
            billing_cycle=data.get("billing_cycle", BillingCycle.MONTHLY),
            unit_price=float(data.get("unit_price", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            status=data.get("status", SubscriptionStatus.ACTIVE),
            current_period_start=data.get("current_period_start", ""),
            current_period_end=data.get("current_period_end", ""),
            next_billing_date=data.get("next_billing_date", ""),
            auto_renew=data.get("auto_renew", True),
            renewal_count=int(data.get("renewal_count", 0)),
            source_app=data.get("source_app", ""),
            notes=data.get("notes", ""),
        )


# ── Credit Note ──────────────────────────────────────────────────────

@dataclass
class CreditNote(BillingEntity):
    """Refund or credit adjustment against an invoice."""

    credit_note_number: str = ""
    invoice_ref: str = ""           # Original invoice number
    reason: str = ""
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    currency: str = DEFAULT_CURRENCY
    status: str = CreditNoteStatus.DRAFT

    @property
    def entity_type(self) -> str:
        return ENTITY_CREDIT_NOTE

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "credit_note_number": self.credit_note_number,
            "invoice_ref": self.invoice_ref,
            "reason": self.reason,
            "line_items": self.line_items,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "total": self.total,
            "currency": self.currency,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CreditNote:
        return cls(
            credit_note_number=data.get("credit_note_number", ""),
            invoice_ref=data.get("invoice_ref", ""),
            reason=data.get("reason", ""),
            line_items=data.get("line_items", []),
            subtotal=float(data.get("subtotal", 0.0)),
            tax_amount=float(data.get("tax_amount", 0.0)),
            total=float(data.get("total", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            status=data.get("status", CreditNoteStatus.DRAFT),
        )


# ── Payment Reminder ─────────────────────────────────────────────────

@dataclass
class PaymentReminder(BillingEntity):
    """Scheduled notification for payment-related events."""

    invoice_ref: str = ""
    customer_ref: Optional[CustomerRef] = None
    reminder_type: str = ReminderType.UPCOMING
    scheduled_date: str = ""        # ISO datetime
    sent_at: str = ""
    channel: str = ReminderChannel.IN_APP
    status: str = ReminderStatus.SCHEDULED
    attempt_count: int = 0
    max_attempts: int = 3
    message_template: str = ""
    notes: str = ""

    @property
    def entity_type(self) -> str:
        return ENTITY_REMINDER

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "invoice_ref": self.invoice_ref,
            "customer_ref": self.customer_ref.to_dict() if self.customer_ref else None,
            "reminder_type": self.reminder_type,
            "scheduled_date": self.scheduled_date,
            "sent_at": self.sent_at,
            "channel": self.channel,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "message_template": self.message_template,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PaymentReminder:
        cust_data = data.get("customer_ref")
        return cls(
            invoice_ref=data.get("invoice_ref", ""),
            customer_ref=CustomerRef.from_dict(cust_data) if cust_data else None,
            reminder_type=data.get("reminder_type", ReminderType.UPCOMING),
            scheduled_date=data.get("scheduled_date", ""),
            sent_at=data.get("sent_at", ""),
            channel=data.get("channel", ReminderChannel.IN_APP),
            status=data.get("status", ReminderStatus.SCHEDULED),
            attempt_count=int(data.get("attempt_count", 0)),
            max_attempts=int(data.get("max_attempts", 3)),
            message_template=data.get("message_template", ""),
            notes=data.get("notes", ""),
        )
