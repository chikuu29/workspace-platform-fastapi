"""
GatewayConfigDoc — Beanie document for the gateway_configs collection.

Per-org/per-app payment gateway credentials and commission settings.
Two-tier model:
  Tier 1 (owner): Org owner's own Razorpay/Stripe keys → direct payment
  Tier 2 (platform): Platform's keys → collect, deduct commission, settle

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from app.core.context import OrgContext
from app.modules.billing.constants import (
    CommissionRateType,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_MIN_COMMISSION,
    ENTITY_GATEWAY_CONFIG,
    GatewayProvider,
    GatewayTier,
)
from app.modules.billing.documents.base import BillingDocument


# ── Embedded Sub-Models ──────────────────────────────────────────────


class CommissionConfigEmbed(BaseModel):
    """
    Platform commission settings — applied to Tier 2 payments.

    Commission is platform-level (same rate for all apps within an org).
    Min/max caps prevent edge cases on very small or very large payments.
    """

    rate_type: str = CommissionRateType.PERCENTAGE
    rate_value: float = DEFAULT_COMMISSION_RATE     # 5% default
    min_commission: float = DEFAULT_MIN_COMMISSION   # ₹10 floor
    max_commission: float = 0.0                      # 0 = no cap


class OwnerCredentialsEmbed(BaseModel):
    """
    Owner's payment gateway API credentials.

    Stored encrypted in MongoDB. Decrypted only at payment time.
    """

    key_id: str = ""
    key_secret: str = ""         # AES-encrypted at rest
    webhook_secret: str = ""     # AES-encrypted at rest


# ── Gateway Config Document ──────────────────────────────────────────


class GatewayConfigDoc(BillingDocument):
    """
    Gateway config Beanie document — stored in the gateway_configs collection.

    Unique per (org_id, app_code). Determines whether payments go
    through the owner's gateway or the platform's gateway.

    Usage:
        doc = GatewayConfigDoc.create_for_org(ctx, entity_type=ENTITY_GATEWAY_CONFIG, ...)
        await doc.insert()

        config = await GatewayConfigDoc.find_active_config(ctx)
    """

    # Tier determines payment flow
    gateway_tier: str = GatewayTier.PLATFORM
    provider: str = GatewayProvider.RAZORPAY

    # Only for tier "owner" — encrypted at rest
    owner_credentials: Optional[OwnerCredentialsEmbed] = None

    # Commission settings (applied platform-wide for Tier 2)
    commission: Optional[CommissionConfigEmbed] = None

    # Activation state
    is_active: bool = True
    verified_at: str = ""     # ISO datetime when credentials were last verified

    class Settings:
        name = "gateway_configs"
        indexes = [
            # One active config per org+app (uniqueness enforced)
            [("_org.org_id", 1), ("_org.app_code", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_active_config(
        cls, ctx: OrgContext
    ) -> Optional["GatewayConfigDoc"]:
        """
        Find the active gateway config for the current org + app.

        There should be at most one active config per (org_id, app_code).
        """
        return await cls.org_find_one(ctx, {
            "_org.app_code": ctx.app_code,
            "is_active": True,
        })

    @property
    def is_owner_tier(self) -> bool:
        """Whether this config uses the owner's own gateway keys."""
        return self.gateway_tier == GatewayTier.OWNER
