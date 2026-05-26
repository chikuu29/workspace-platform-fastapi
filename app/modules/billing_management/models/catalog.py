"""
CatalogItem — represents anything that can be billed.

Products (physical goods), services, and subscription plans all live
in the billing_catalog collection. Each item has:
- A unique `code` per org (e.g. "GYM_PRO", "ROOM_RENT")
- HSN/SAC code for GST compliance
- Tax category for automatic GST rate resolution
- Optional app_tags to scope items to specific apps

Gym subscription plans, hostel room charges, and any future app's
billable items all go through this unified catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.modules.billing_management.constants import (
    BillingCycle,
    CatalogItemType,
    DEFAULT_CURRENCY,
    ENTITY_CATALOG,
    GSTCategory,
)
from app.modules.billing_management.models.base import BillingEntity


@dataclass
class CatalogItem(BillingEntity):
    """
    A billable item in the organization's catalog.

    item_type determines whether it's a one-time product/service
    or a recurring subscription plan. billing_cycle only applies
    to subscription_plan items.
    """

    # Identity
    name: str = ""
    code: str = ""                               # Unique per org
    description: str = ""

    # Classification
    item_type: str = CatalogItemType.SERVICE      # product | service | subscription_plan

    # Pricing
    unit_price: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # Tax
    tax_category: str = GSTCategory.HIGHER        # Maps to GST rate via GST_RATE_MAP
    hsn_sac_code: str = ""                        # HSN (goods) or SAC (services) code
    is_tax_inclusive: bool = False                 # Whether unit_price includes tax

    # Subscription-specific
    billing_cycle: str = BillingCycle.ONE_TIME
    trial_days: int = 0

    # Activation
    is_active: bool = True

    # Cross-app tagging — empty means available to all apps
    app_tags: List[str] = field(default_factory=list)

    # Flexible metadata for app-specific extensions
    # e.g., {"features": ["wifi", "ac"], "accent_color": "blue"}
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def entity_type(self) -> str:
        return ENTITY_CATALOG

    def to_data_dict(self) -> Dict[str, Any]:
        """Serialize for MongoDB's `data` field."""
        return {
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "item_type": self.item_type,
            "unit_price": self.unit_price,
            "currency": self.currency,
            "tax_category": self.tax_category,
            "hsn_sac_code": self.hsn_sac_code,
            "is_tax_inclusive": self.is_tax_inclusive,
            "billing_cycle": self.billing_cycle,
            "trial_days": self.trial_days,
            "is_active": self.is_active,
            "app_tags": self.app_tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CatalogItem:
        """Reconstruct from MongoDB `data` field."""
        return cls(
            name=data.get("name", ""),
            code=data.get("code", ""),
            description=data.get("description", ""),
            item_type=data.get("item_type", CatalogItemType.SERVICE),
            unit_price=float(data.get("unit_price", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            tax_category=data.get("tax_category", GSTCategory.HIGHER),
            hsn_sac_code=data.get("hsn_sac_code", ""),
            is_tax_inclusive=data.get("is_tax_inclusive", False),
            billing_cycle=data.get("billing_cycle", BillingCycle.ONE_TIME),
            trial_days=int(data.get("trial_days", 0)),
            is_active=data.get("is_active", True),
            app_tags=data.get("app_tags", []),
            metadata=data.get("metadata", {}),
        )
