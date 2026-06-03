"""
TaxProfileDoc — Beanie document for the tax_profiles collection.

Represents an org-level GST registration and default tax configuration.
Supports multiple profiles per org for multi-state GST compliance.

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed

from app.core.context import OrgContext
from app.modules.billing.constants import (
    ENTITY_TAX_PROFILE,
    GSTCategory,
    TaxType,
)
from app.modules.billing.documents.base import BillingDocument


class TaxProfileDoc(BillingDocument):
    """
    Tax profile Beanie document — stored in the tax_profiles collection.

    Each profile represents a GSTIN registration with state-level
    configuration and default tax rates.

    Usage:
        doc = TaxProfileDoc.create_for_org(ctx, entity_type=ENTITY_TAX_PROFILE, ...)
        await doc.insert()

        default = await TaxProfileDoc.find_default(ctx)
        profile = await TaxProfileDoc.find_by_gstin(ctx, "29AABCU9603R1ZM")
    """

    # Profile identity
    profile_name: str = ""
    gstin: Indexed(str) = ""              # e.g. "29AABCU9603R1ZM"
    legal_name: str = ""                  # Legal entity name
    trade_name: str = ""                  # Trade/brand name

    # State details — used for inter-state determination
    state_code: str = ""                  # 2-digit state code (e.g. "29")
    state_name: str = ""

    # Tax configuration
    tax_type: str = TaxType.GST
    default_tax_category: str = GSTCategory.HIGHER  # Default GST rate category
    is_composition_scheme: bool = False

    # Default flag — one profile per org is the primary
    is_default: bool = False

    class Settings:
        name = "tax_profiles"
        indexes = [
            # GSTIN uniqueness per org
            [("_org.org_id", 1), ("gstin", 1)],
            # Default profile lookup
            [("_org.org_id", 1), ("is_default", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_default(
        cls, ctx: OrgContext
    ) -> Optional["TaxProfileDoc"]:
        """Find the default tax profile for the current org."""
        return await cls.org_find_one(ctx, {"is_default": True})

    @classmethod
    async def find_by_gstin(
        cls, ctx: OrgContext, gstin: str
    ) -> Optional["TaxProfileDoc"]:
        """Find a tax profile by its GSTIN number."""
        return await cls.org_find_one(ctx, {"gstin": gstin})

    @classmethod
    async def list_all(
        cls,
        ctx: OrgContext,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> List["TaxProfileDoc"]:
        """List all tax profiles for the org, default first."""
        return await cls.org_find(
            ctx,
            {},
            sort=[("is_default", -1), ("profile_name", 1)],
            skip=skip,
            limit=limit,
        )
