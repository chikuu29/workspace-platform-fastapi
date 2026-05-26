"""
Settlement — platform → owner commission & payout ledger.

Each settlement aggregates platform-tier payments for a period,
computes total commission, and tracks the payout to the org owner.
Supports both manual and automatic settlement modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.modules.billing_management.constants import (
    DEFAULT_CURRENCY,
    ENTITY_SETTLEMENT,
    SettlementMode,
    SettlementStatus,
)
from app.modules.billing_management.models.base import BillingEntity


@dataclass
class Settlement(BillingEntity):
    """Platform → owner settlement record."""

    # Identity
    settlement_number: str = ""     # STL-202605-0001

    # Period
    period_start: str = ""          # ISO date
    period_end: str = ""

    # Money breakdown
    total_collected: float = 0.0    # Total payments via platform gateway
    total_commission: float = 0.0   # Platform's cut
    total_refunds: float = 0.0      # Refunds during period
    total_adjustments: float = 0.0  # Manual adjustments
    net_payable: float = 0.0        # What owner receives
    currency: str = DEFAULT_CURRENCY

    # Settlement execution
    status: str = SettlementStatus.PENDING
    mode: str = SettlementMode.MANUAL   # manual | automatic
    paid_via: str = ""                  # bank_transfer, upi, etc.
    paid_at: str = ""                   # ISO datetime
    reference_id: str = ""              # Bank txn reference

    # Linked payments (payment_numbers)
    payment_refs: List[str] = field(default_factory=list)
    payment_count: int = 0

    notes: str = ""

    @property
    def entity_type(self) -> str:
        return ENTITY_SETTLEMENT

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "settlement_number": self.settlement_number,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_collected": self.total_collected,
            "total_commission": self.total_commission,
            "total_refunds": self.total_refunds,
            "total_adjustments": self.total_adjustments,
            "net_payable": self.net_payable,
            "currency": self.currency,
            "status": self.status,
            "mode": self.mode,
            "paid_via": self.paid_via,
            "paid_at": self.paid_at,
            "reference_id": self.reference_id,
            "payment_refs": self.payment_refs,
            "payment_count": self.payment_count,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Settlement:
        return cls(
            settlement_number=data.get("settlement_number", ""),
            period_start=data.get("period_start", ""),
            period_end=data.get("period_end", ""),
            total_collected=float(data.get("total_collected", 0.0)),
            total_commission=float(data.get("total_commission", 0.0)),
            total_refunds=float(data.get("total_refunds", 0.0)),
            total_adjustments=float(data.get("total_adjustments", 0.0)),
            net_payable=float(data.get("net_payable", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            status=data.get("status", SettlementStatus.PENDING),
            mode=data.get("mode", SettlementMode.MANUAL),
            paid_via=data.get("paid_via", ""),
            paid_at=data.get("paid_at", ""),
            reference_id=data.get("reference_id", ""),
            payment_refs=data.get("payment_refs", []),
            payment_count=int(data.get("payment_count", 0)),
            notes=data.get("notes", ""),
        )
