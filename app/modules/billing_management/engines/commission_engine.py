"""
Commission Engine — pure computation for platform commission.

Commission is platform-level (same rate for all apps).
Applied only to Tier 2 (platform gateway) payments.

Supports:
 - Percentage-based commission (e.g. 5% of payment)
 - Fixed-amount commission (e.g. ₹50 per transaction)
 - Min/max commission caps
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.modules.billing_management.constants import (
    CommissionRateType,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_MIN_COMMISSION,
)


@dataclass(frozen=True, slots=True)
class CommissionResult:
    """Result of commission computation."""
    payment_amount: float
    commission_amount: float
    net_to_owner: float
    rate_type: str
    rate_value: float


def compute_commission(
    payment_amount: float,
    rate_type: str = CommissionRateType.PERCENTAGE,
    rate_value: float = DEFAULT_COMMISSION_RATE,
    min_commission: float = DEFAULT_MIN_COMMISSION,
    max_commission: float = 0.0,
) -> CommissionResult:
    """
    Compute platform commission for a payment.

    Args:
        payment_amount: The total payment amount.
        rate_type: "percentage" or "fixed".
        rate_value: Commission rate (e.g. 5.0 for 5% or 50.0 for ₹50 fixed).
        min_commission: Minimum commission per transaction (floor).
        max_commission: Maximum commission per transaction (cap). 0 = no cap.

    Returns:
        CommissionResult with commission amount and net amount to owner.
    """
    if payment_amount <= 0:
        return CommissionResult(
            payment_amount=payment_amount,
            commission_amount=0.0,
            net_to_owner=payment_amount,
            rate_type=rate_type,
            rate_value=rate_value,
        )

    # Calculate raw commission
    if rate_type == CommissionRateType.PERCENTAGE:
        raw_commission = round(payment_amount * rate_value / 100, 2)
    elif rate_type == CommissionRateType.FIXED:
        raw_commission = round(rate_value, 2)
    else:
        raw_commission = 0.0

    # Apply floor (minimum commission)
    commission = max(raw_commission, min_commission)

    # Apply cap (maximum commission)
    if max_commission > 0:
        commission = min(commission, max_commission)

    # Commission can never exceed the payment amount
    commission = min(commission, payment_amount)
    commission = round(commission, 2)

    net_to_owner = round(payment_amount - commission, 2)

    return CommissionResult(
        payment_amount=round(payment_amount, 2),
        commission_amount=commission,
        net_to_owner=net_to_owner,
        rate_type=rate_type,
        rate_value=rate_value,
    )
