"""
TaxProfileDoc — Beanie document for the tax_profiles collection.

Represents an org-level GST registration and default tax configuration.
Supports multiple profiles per org for multi-state GST compliance.

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from beanie import Indexed
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.modules.billing.constants import (
    ENTITY_TAX_PROFILE,
    GSTCategory,
    TaxType,
)
from app.modules.billing.documents.base import BillingDocument


class TaxProfileData(BaseModel):
    """Business fields for TaxProfile stored nested under 'data'."""
    profile_name: str = ""
    gstin: str = ""
    legal_name: str = ""
    trade_name: str = ""
    state_code: str = ""
    state_name: str = ""
    tax_type: str = TaxType.GST
    default_tax_category: str = GSTCategory.HIGHER
    is_composition_scheme: bool = False
    is_default: bool = False


class TaxProfileDoc(BillingDocument):
    """
    Tax profile Beanie document — stored in the tax_profiles collection.

    Each profile represents a GSTIN registration with state-level
    configuration and default tax rates.
    """

    data: TaxProfileData = Field(default_factory=TaxProfileData)

    # ── Properties for flat attribute access compatibility ──

    @property
    def profile_name(self) -> str:
        return self.data.profile_name

    @profile_name.setter
    def profile_name(self, value: str) -> None:
        self.data.profile_name = value

    @property
    def gstin(self) -> str:
        return self.data.gstin

    @gstin.setter
    def gstin(self, value: str) -> None:
        self.data.gstin = value

    @property
    def legal_name(self) -> str:
        return self.data.legal_name

    @legal_name.setter
    def legal_name(self, value: str) -> None:
        self.data.legal_name = value

    @property
    def trade_name(self) -> str:
        return self.data.trade_name

    @trade_name.setter
    def trade_name(self, value: str) -> None:
        self.data.trade_name = value

    @property
    def state_code(self) -> str:
        return self.data.state_code

    @state_code.setter
    def state_code(self, value: str) -> None:
        self.data.state_code = value

    @property
    def state_name(self) -> str:
        return self.data.state_name

    @state_name.setter
    def state_name(self, value: str) -> None:
        self.data.state_name = value

    @property
    def tax_type(self) -> str:
        return self.data.tax_type

    @tax_type.setter
    def tax_type(self, value: str) -> None:
        self.data.tax_type = value

    @property
    def default_tax_category(self) -> str:
        return self.data.default_tax_category

    @default_tax_category.setter
    def default_tax_category(self, value: str) -> None:
        self.data.default_tax_category = value

    @property
    def is_composition_scheme(self) -> bool:
        return self.data.is_composition_scheme

    @is_composition_scheme.setter
    def is_composition_scheme(self, value: bool) -> None:
        self.data.is_composition_scheme = value

    @property
    def is_default(self) -> bool:
        return self.data.is_default

    @is_default.setter
    def is_default(self, value: bool) -> None:
        self.data.is_default = value

    class Settings:
        name = "tax_profiles"
        indexes = [
            # GSTIN uniqueness per org
            [("_org.org_id", 1), ("data.gstin", 1)],
            # Default profile lookup
            [("_org.org_id", 1), ("data.is_default", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_default(
        cls, ctx: OrgContext
    ) -> Optional["TaxProfileDoc"]:
        """Find the default tax profile for the current org."""
        return await cls.org_find_one(ctx, {"data.is_default": True})

    @classmethod
    async def find_by_gstin(
        cls, ctx: OrgContext, gstin: str
    ) -> Optional["TaxProfileDoc"]:
        """Find a tax profile by its GSTIN number."""
        return await cls.org_find_one(ctx, {"data.gstin": gstin})

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
            sort=[("data.is_default", -1), ("data.profile_name", 1)],
            skip=skip,
            limit=limit,
        )
