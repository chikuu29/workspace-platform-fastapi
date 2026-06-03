"""
Payment Gateway ABC — abstract base for payment gateway integrations.

Designed now, implemented later. Each provider (Razorpay, Stripe,
Cashfree) will implement this interface. PaymentService uses this
abstraction — never talks to providers directly.

Future implementation:
    from app.modules.billing.gateways.razorpay import RazorpayGateway
    gateway = RazorpayGateway(api_key, api_secret)
    order = await gateway.create_order(5000.0, "INR", "RCT/2026-27/0001")
    result = await gateway.verify_payment(payment_id, order_id, signature)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict


# ── Gateway Result Types ─────────────────────────────────────────────
# Immutable data containers returned by gateway operations.


@dataclass(frozen=True, slots=True)
class GatewayOrderResult:
    """Result from creating a gateway payment order."""

    gateway_order_id: str       # Razorpay order_id / Stripe payment_intent
    amount: float
    currency: str
    checkout_url: str = ""      # URL for hosted checkout (if applicable)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayVerifyResult:
    """Result from verifying a gateway payment callback."""

    verified: bool
    gateway_payment_id: str = ""
    gateway_order_id: str = ""
    amount: float = 0.0
    method: str = ""            # card, upi, netbanking, wallet
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GatewayRefundResult:
    """Result from initiating a gateway refund."""

    refund_id: str = ""
    amount: float = 0.0
    status: str = ""            # processed, pending, failed
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Gateway Abstract Base ────────────────────────────────────────────


class PaymentGateway(ABC):
    """
    Abstract base for payment gateway integrations.

    Each provider (Razorpay, Stripe, Cashfree) implements this interface.
    PaymentService uses this abstraction to create orders, verify payments,
    and initiate refunds — never talking to providers directly.

    Concrete implementations:
        - gateways/razorpay.py   (future)
        - gateways/stripe.py     (future)
        - gateways/cashfree.py   (future)
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Provider identifier: 'razorpay', 'stripe', 'cashfree'.

        Used for logging, tracking, and PaymentDoc.gateway_provider field.
        """
        ...

    @abstractmethod
    async def create_order(
        self,
        amount: float,
        currency: str,
        receipt_id: str,
        **kwargs: Any,
    ) -> GatewayOrderResult:
        """
        Create a payment order on the gateway.

        The receipt_id links the gateway order to our billing number.
        Returns a GatewayOrderResult with the gateway's order ID
        and optional checkout URL.
        """
        ...

    @abstractmethod
    async def verify_payment(
        self,
        payment_id: str,
        order_id: str,
        signature: str,
    ) -> GatewayVerifyResult:
        """
        Verify a payment callback/webhook from the gateway.

        Called after the frontend captures payment and sends back
        the gateway's payment_id, order_id, and signature.

        Returns GatewayVerifyResult with verification status.
        """
        ...

    @abstractmethod
    async def initiate_refund(
        self,
        payment_id: str,
        amount: float,
        reason: str = "",
    ) -> GatewayRefundResult:
        """
        Initiate a refund on the gateway.

        Partial refunds are supported if the gateway allows them.
        """
        ...

    @abstractmethod
    async def check_payment_status(self, payment_id: str) -> str:
        """
        Poll payment status from the gateway.

        Used for async verification when webhooks are delayed.
        Returns: 'captured', 'pending', 'failed', 'refunded'.
        """
        ...
