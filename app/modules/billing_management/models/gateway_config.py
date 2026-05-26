"""
GatewayConfig — per-org/per-app payment gateway credentials.

Two-tier model:
  Tier 1 (owner): Org owner's own Razorpay/Stripe keys → direct payment
  Tier 2 (platform): Platform's keys → collect, deduct commission, settle

Commission is platform-level (same rate for all apps within an org).
Gateway config is unique per org+app combination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.modules.billing_management.constants import (
    CommissionRateType,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_MIN_COMMISSION,
    ENTITY_GATEWAY_CONFIG,
    GatewayProvider,
    GatewayTier,
)
from app.modules.billing_management.models.base import BillingEntity


@dataclass
class CommissionConfig:
    """
    Platform commission settings.

    Commission is platform-level — same rate for all apps.
    Applied only to platform-tier (Tier 2) payments.
    """
    rate_type: str = CommissionRateType.PERCENTAGE
    rate_value: float = DEFAULT_COMMISSION_RATE   # 5% default
    min_commission: float = DEFAULT_MIN_COMMISSION  # ₹10 floor
    max_commission: float = 0.0                   # 0 = no cap

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rate_type": self.rate_type,
            "rate_value": self.rate_value,
            "min_commission": self.min_commission,
            "max_commission": self.max_commission,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CommissionConfig:
        return cls(
            rate_type=data.get("rate_type", CommissionRateType.PERCENTAGE),
            rate_value=float(data.get("rate_value", DEFAULT_COMMISSION_RATE)),
            min_commission=float(data.get("min_commission", DEFAULT_MIN_COMMISSION)),
            max_commission=float(data.get("max_commission", 0.0)),
        )


@dataclass
class OwnerCredentials:
    """
    Owner's payment gateway API credentials.

    Stored encrypted in MongoDB. Decrypted only at payment time.
    """
    key_id: str = ""
    key_secret: str = ""        # AES-encrypted
    webhook_secret: str = ""    # AES-encrypted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key_id": self.key_id,
            "key_secret": self.key_secret,
            "webhook_secret": self.webhook_secret,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OwnerCredentials:
        return cls(
            key_id=data.get("key_id", ""),
            key_secret=data.get("key_secret", ""),
            webhook_secret=data.get("webhook_secret", ""),
        )


@dataclass
class GatewayConfig(BillingEntity):
    """
    Payment gateway configuration for an org+app.

    Unique per (org_id, app_code). Determines whether payments
    go through the owner's gateway or the platform's gateway.
    """
    gateway_tier: str = GatewayTier.PLATFORM
    provider: str = GatewayProvider.RAZORPAY

    # Only for tier "owner" — encrypted at rest
    owner_credentials: Optional[OwnerCredentials] = None

    # Commission settings (applied platform-wide for Tier 2)
    commission: Optional[CommissionConfig] = None

    is_active: bool = True
    verified_at: str = ""     # ISO datetime when credentials were last verified

    @property
    def entity_type(self) -> str:
        return ENTITY_GATEWAY_CONFIG

    @property
    def is_owner_tier(self) -> bool:
        return self.gateway_tier == GatewayTier.OWNER

    def to_data_dict(self) -> Dict[str, Any]:
        return {
            "gateway_tier": self.gateway_tier,
            "provider": self.provider,
            "owner_credentials": (
                self.owner_credentials.to_dict() if self.owner_credentials else None
            ),
            "commission": (
                self.commission.to_dict() if self.commission else None
            ),
            "is_active": self.is_active,
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GatewayConfig:
        creds_data = data.get("owner_credentials")
        comm_data = data.get("commission")
        return cls(
            gateway_tier=data.get("gateway_tier", GatewayTier.PLATFORM),
            provider=data.get("provider", GatewayProvider.RAZORPAY),
            owner_credentials=(
                OwnerCredentials.from_dict(creds_data) if creds_data else None
            ),
            commission=(
                CommissionConfig.from_dict(comm_data) if comm_data else None
            ),
            is_active=data.get("is_active", True),
            verified_at=data.get("verified_at", ""),
        )
