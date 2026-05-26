"""
Pricing Engine — pure computation for line-item pricing.

Handles:
 - Gross amount (quantity × unit_price)
 - Discounts (percentage or fixed)
 - Taxable amount (gross - discount)
 - Line total (taxable + tax)

No I/O, no side effects — fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.modules.billing_management.constants import DiscountType


@dataclass(frozen=True, slots=True)
class LineCalculation:
    """Result of line-item pricing computation."""
    gross_amount: float       # quantity × unit_price
    discount_amount: float    # Actual discount in currency
    taxable_amount: float     # gross - discount (before tax)
    tax_amount: float         # From tax engine
    line_total: float         # taxable + tax


def compute_discount(
    gross_amount: float,
    discount_type: str,
    discount_value: float,
) -> float:
    """
    Compute the discount amount in currency.

    Args:
        gross_amount: quantity × unit_price before any discount.
        discount_type: "percentage", "fixed", or "none".
        discount_value: The discount value (e.g. 10 for 10% or ₹10).

    Returns:
        Actual discount amount. Never exceeds gross_amount.
    """
    if discount_type == DiscountType.NONE or discount_value <= 0:
        return 0.0

    if discount_type == DiscountType.PERCENTAGE:
        # Cap at 100% to prevent negative amounts
        capped_pct = min(discount_value, 100.0)
        discount = round(gross_amount * capped_pct / 100, 2)
    elif discount_type == DiscountType.FIXED:
        discount = round(min(discount_value, gross_amount), 2)
    else:
        discount = 0.0

    return discount


def compute_line_pricing(
    quantity: float,
    unit_price: float,
    discount_type: str = DiscountType.NONE,
    discount_value: float = 0.0,
    tax_amount: float = 0.0,
) -> LineCalculation:
    """
    Compute full pricing for a single line item.

    Args:
        quantity: Number of units.
        unit_price: Price per unit.
        discount_type: Type of discount applied.
        discount_value: Discount value (percentage or fixed amount).
        tax_amount: Tax computed by the tax engine (passed in).

    Returns:
        LineCalculation with all computed fields.
    """
    gross = round(quantity * unit_price, 2)
    discount = compute_discount(gross, discount_type, discount_value)
    taxable = round(gross - discount, 2)
    total = round(taxable + tax_amount, 2)

    return LineCalculation(
        gross_amount=gross,
        discount_amount=discount,
        taxable_amount=taxable,
        tax_amount=round(tax_amount, 2),
        line_total=total,
    )


def compute_invoice_totals(
    line_calculations: list[LineCalculation],
) -> tuple[float, float, float, float]:
    """
    Aggregate line calculations into invoice-level totals.

    Returns:
        Tuple of (subtotal, total_discount, total_tax, grand_total).
    """
    subtotal = sum(lc.taxable_amount for lc in line_calculations)
    total_discount = sum(lc.discount_amount for lc in line_calculations)
    total_tax = sum(lc.tax_amount for lc in line_calculations)
    grand_total = sum(lc.line_total for lc in line_calculations)

    return (
        round(subtotal, 2),
        round(total_discount, 2),
        round(total_tax, 2),
        round(grand_total, 2),
    )
