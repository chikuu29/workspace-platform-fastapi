"""
Line item schemas — discriminated by item_type.

Three item types, each with its own required fields:
  - goods:        Physical products — requires HSN code
  - service:      Service items — requires SAC code
  - subscription: Recurring plans — requires plan_code + period

The APP MODULE validates the item exists and provides the REAL price.
Billing trusts the price it receives (no catalog lookup needed).
The discriminated union ensures each item type carries the right fields.

Flow:
    Gym Service → validates member + plan → knows price is ₹5000
    Gym Service → builds ServiceLineItem(item_type="service", unit_price=5000, ...)
    Gym Service → calls InvoiceService.create_invoice(items=[...])
    Billing     → trusts the price, computes tax/discount/totals
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

from app.modules.billing_management.constants import DiscountType


# ── Base Line Item (fields shared by all item types) ─────────────────


class _BaseLineItem(BaseModel):
    """
    Shared fields across all item types.

    unit_price is the VERIFIED price from the calling app module.
    Billing trusts it because the app already validated against its
    own catalog/plan data.
    """

    description: str = Field(..., min_length=1, max_length=500)
    quantity: float = Field(
        ...,
        gt=0,
        le=10000,
        description="Must be positive",
    )
    unit_price: float = Field(
        ...,
        ge=0,
        description="Verified price from the calling app module",
    )
    discount_type: str = Field(
        DiscountType.NONE,
        description="percentage | fixed | none",
    )
    discount_value: float = Field(0.0, ge=0)
    hsn_sac_code: str = Field(
        "",
        max_length=8,
        description="HSN code (goods) or SAC code (services)",
    )
    tax_category: str = Field(
        "higher",
        description="GST slab: exempt, nil, low, standard, higher, luxury",
    )
    # Traces back to the originating app's item code for auditability
    source_item_code: str = Field(
        "",
        description="Item code from the source app (gym plan code, hostel room, etc.)",
    )

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, v: str) -> str:
        """Ensure discount_type is a valid enum value."""
        allowed = {e.value for e in DiscountType}
        if v not in allowed:
            msg = f"discount_type must be one of: {', '.join(sorted(allowed))}"
            raise ValueError(msg)
        return v


# ── Goods (physical products) ────────────────────────────────────────


class GoodsLineItem(_BaseLineItem):
    """
    Physical goods — HSN code is required for GST compliance.

    Examples: gym supplements, equipment, merchandise, printed materials.
    """

    item_type: Literal["goods"] = "goods"
    hsn_sac_code: str = Field(
        ...,
        min_length=4,
        max_length=8,
        description="HSN code is REQUIRED for goods (GST compliance)",
    )
    unit_of_measurement: str = Field(
        "pcs",
        description="Unit: pcs, kg, litre, box, etc.",
    )


# ── Service ──────────────────────────────────────────────────────────


class ServiceLineItem(_BaseLineItem):
    """
    Service items — SAC code is required for GST compliance.

    Examples: gym training sessions, hostel room service, consulting hours.
    """

    item_type: Literal["service"] = "service"
    hsn_sac_code: str = Field(
        ...,
        min_length=4,
        max_length=8,
        description="SAC code is REQUIRED for services (GST compliance)",
    )
    service_date: str = Field(
        "",
        description="Date service was rendered (ISO format)",
    )
    service_period_start: str = Field(
        "",
        description="Service period start (ISO date)",
    )
    service_period_end: str = Field(
        "",
        description="Service period end (ISO date)",
    )


# ── Subscription ─────────────────────────────────────────────────────


class SubscriptionLineItem(_BaseLineItem):
    """
    Subscription/plan items — links to a recurring plan.

    Examples: monthly gym membership, quarterly hostel stay, annual package.
    """

    item_type: Literal["subscription"] = "subscription"
    plan_code: str = Field(
        ...,
        min_length=1,
        description="Subscription plan code from the source app",
    )
    billing_cycle: str = Field(
        "monthly",
        description="one_time, daily, weekly, monthly, quarterly, half_yearly, yearly",
    )
    period_start: str = Field(
        ...,
        description="Subscription period start (ISO date)",
    )
    period_end: str = Field(
        ...,
        description="Subscription period end (ISO date)",
    )


# ── Discriminated Union ──────────────────────────────────────────────
# Pydantic auto-selects the correct schema based on the item_type field.
#
# Example payloads:
#   {"item_type": "service", "description": "Pro Gym", ...}  → ServiceLineItem
#   {"item_type": "goods", "description": "Whey Protein", ...} → GoodsLineItem
#   {"item_type": "subscription", "plan_code": "GYM_PRO", ...} → SubscriptionLineItem

LineItemInput = Annotated[
    Union[GoodsLineItem, ServiceLineItem, SubscriptionLineItem],
    Field(discriminator="item_type"),
]


# ── Computed Line Item (response-only) ───────────────────────────────


class LineItemResponse(BaseModel):
    """
    Line item in invoice responses — includes server-computed fields.

    This is what the frontend receives. All financial computation
    (discount_amount, tax_rate, tax_amount, taxable_amount, line_total)
    is done server-side by PricingEngine + TaxEngine.
    """

    # Item identity
    item_type: str
    source_item_code: str = ""
    description: str
    hsn_sac_code: str = ""

    # Input fields
    quantity: float
    unit_price: float
    discount_type: str
    discount_value: float

    # Computed by PricingEngine
    discount_amount: float

    # Computed by TaxEngine
    tax_category: str
    tax_rate: float
    tax_amount: float

    # Computed totals
    taxable_amount: float
    line_total: float

    # Type-specific fields (present depending on item_type)
    unit_of_measurement: str | None = None    # Goods
    service_date: str | None = None           # Service
    service_period_start: str | None = None   # Service
    service_period_end: str | None = None     # Service
    plan_code: str | None = None              # Subscription
    billing_cycle: str | None = None          # Subscription
    period_start: str | None = None           # Subscription
    period_end: str | None = None             # Subscription
