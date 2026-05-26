"""
Payment — records a payment against an invoice.

Supports cash, UPI, card, net banking, gateway, and other methods.
For gateway-mediated payments, tracks the gateway tier (owner vs
platform), gateway IDs, and commission details.

Commission fields are only populated for platform-tier payments:
  - commission_amount: platform's cut
  - net_to_owner: amount owed to the org owner after commission
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.modules.billing_management.constants import (
    DEFAULT_CURRENCY,
    ENTITY_PAYMENT,
    GatewayProvider,
    GatewayTier,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.billing_management.models.base import BillingEntity


@dataclass
class Payment(BillingEntity):
    """A payment record — linked to an invoice via invoice_ref."""

    # Identity
    payment_number: str = ""        # PAY-INV-202605-0001

    # Invoice linkage
    invoice_ref: str = ""           # invoice_number of the linked invoice

    # Amount
    amount: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Method
    method: str = PaymentMethod.CASH

    # Gateway details (only for gateway-mediated payments)
    gateway_tier: str = ""          # "owner" | "platform" | ""
    gateway_provider: str = ""      # "razorpay" | "stripe" | ""
    gateway_payment_id: str = ""    # Provider's payment ID
    gateway_order_id: str = ""      # Provider's order ID
    gateway_signature: str = ""     # Verification signature

    # Commission (only for platform-tier payments)
    commission_rate: float = 0.0    # e.g. 5.0 (%)
    commission_amount: float = 0.0  # Platform's cut
    net_to_owner: float = 0.0      # Amount owed to org owner

    # Status
    status: str = PaymentStatus.CAPTURED

    # Dates
    payment_date: str = ""          # ISO format

    # Reference
    transaction_ref: str = ""       # External reference (bank txn ID, UPI ref)
    notes: str = ""

    @property
    def entity_type(self) -> str:
        return ENTITY_PAYMENT

    @property
    def is_platform_payment(self) -> bool:
        """Whether this payment went through the platform's gateway."""
        return self.gateway_tier == GatewayTier.PLATFORM

    def to_data_dict(self) -> Dict[str, Any]:
        """Serialize for MongoDB's `data` field."""
        return {
            "payment_number": self.payment_number,
            "invoice_ref": self.invoice_ref,
            "amount": self.amount,
            "currency": self.currency,
            "method": self.method,
            "gateway_tier": self.gateway_tier,
            "gateway_provider": self.gateway_provider,
            "gateway_payment_id": self.gateway_payment_id,
            "gateway_order_id": self.gateway_order_id,
            "gateway_signature": self.gateway_signature,
            "commission_rate": self.commission_rate,
            "commission_amount": self.commission_amount,
            "net_to_owner": self.net_to_owner,
            "status": self.status,
            "payment_date": self.payment_date,
            "transaction_ref": self.transaction_ref,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Payment:
        """Reconstruct from MongoDB `data` field."""
        return cls(
            payment_number=data.get("payment_number", ""),
            invoice_ref=data.get("invoice_ref", ""),
            amount=float(data.get("amount", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            method=data.get("method", PaymentMethod.CASH),
            gateway_tier=data.get("gateway_tier", ""),
            gateway_provider=data.get("gateway_provider", ""),
            gateway_payment_id=data.get("gateway_payment_id", ""),
            gateway_order_id=data.get("gateway_order_id", ""),
            gateway_signature=data.get("gateway_signature", ""),
            commission_rate=float(data.get("commission_rate", 0.0)),
            commission_amount=float(data.get("commission_amount", 0.0)),
            net_to_owner=float(data.get("net_to_owner", 0.0)),
            status=data.get("status", PaymentStatus.CAPTURED),
            payment_date=data.get("payment_date", ""),
            transaction_ref=data.get("transaction_ref", ""),
            notes=data.get("notes", ""),
        )
