"""
Tax Engine — pure GST computation, no I/O.

Computes Indian GST (Goods & Services Tax) based on:
 - Seller's state code (from GSTIN or tax profile)
 - Place of supply (buyer's state code)
 - Tax category → rate lookup

Rules:
 - Same state (intra-state): CGST (half) + SGST (half)
 - Different state (inter-state): IGST (full)
 - Composition scheme: flat lower rate (simplified)

The seller's GSTIN and buyer's GSTIN are passed via the API at
invoice creation time — not pre-configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.modules.billing.constants import (
    DEFAULT_TAX_RATE,
    GST_RATE_MAP,
    GSTCategory,
    TaxType,
)


# ── Tax Computation Result ───────────────────────────────────────────
# Pure data container — the output of tax engine computations.
# Frozen dataclass ensures immutability (appropriate for computation results).


@dataclass(frozen=True, slots=True)
class TaxBreakdown:
    """
    Itemized tax computation result.

    For intra-state: cgst + sgst = total_tax
    For inter-state: igst = total_tax
    """

    tax_type: str = "gst"
    tax_rate: float = 0.0
    taxable_amount: float = 0.0
    cgst_rate: float = 0.0
    cgst_amount: float = 0.0
    sgst_rate: float = 0.0
    sgst_amount: float = 0.0
    igst_rate: float = 0.0
    igst_amount: float = 0.0
    total_tax: float = 0.0
    is_inter_state: bool = False
    seller_gstin: str = ""
    buyer_gstin: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses and MongoDB storage."""
        return {
            "tax_type": self.tax_type,
            "tax_rate": self.tax_rate,
            "taxable_amount": self.taxable_amount,
            "cgst_rate": self.cgst_rate,
            "cgst_amount": self.cgst_amount,
            "sgst_rate": self.sgst_rate,
            "sgst_amount": self.sgst_amount,
            "igst_rate": self.igst_rate,
            "igst_amount": self.igst_amount,
            "total_tax": self.total_tax,
            "is_inter_state": self.is_inter_state,
            "seller_gstin": self.seller_gstin,
            "buyer_gstin": self.buyer_gstin,
        }

    @classmethod
    def zero(cls) -> TaxBreakdown:
        """No-tax breakdown for exempt items."""
        return cls(tax_type="none", tax_rate=0.0)


def extract_state_code(gstin: str) -> str:
    """
    Extract 2-digit state code from a GSTIN.

    GSTIN format: 29AABCU9603R1ZM
    First 2 digits = state code (e.g. "29" = Karnataka).
    Returns empty string if GSTIN is invalid/missing.
    """
    if gstin and len(gstin) >= 2 and gstin[:2].isdigit():
        return gstin[:2]
    return ""


def resolve_gst_rate(tax_category: str, custom_rate: Optional[float] = None) -> float:
    """
    Resolve the effective GST rate for a given tax category.

    If custom_rate is provided, it overrides the category lookup.
    This allows per-item rate customization while keeping category
    as the default behavior.
    """
    if custom_rate is not None and custom_rate >= 0:
        return custom_rate

    try:
        category = GSTCategory(tax_category)
        return GST_RATE_MAP.get(category, DEFAULT_TAX_RATE)
    except ValueError:
        # Unknown category → fall back to default (18%)
        return DEFAULT_TAX_RATE


def is_inter_state(seller_state: str, supply_state: str) -> bool:
    """
    Determine if a transaction is inter-state.

    Inter-state → IGST applies (single tax to central govt).
    Intra-state → CGST + SGST applies (split between central + state).
    """
    if not seller_state or not supply_state:
        # If state codes are missing, default to intra-state
        # (safer — avoids incorrect IGST on local transactions)
        return False
    return seller_state != supply_state


def compute_line_tax(
    taxable_amount: float,
    tax_category: str,
    seller_gstin: str = "",
    place_of_supply: str = "",
    custom_rate: Optional[float] = None,
) -> TaxBreakdown:
    """
    Compute GST for a single line item.

    Args:
        taxable_amount: Amount after discount, before tax.
        tax_category: GST category (exempt, low, standard, higher, luxury).
        seller_gstin: Seller's GSTIN (for state code extraction).
        place_of_supply: Buyer's state code or GSTIN.
        custom_rate: Override the category-based rate.

    Returns:
        TaxBreakdown with CGST/SGST or IGST amounts.
    """
    if taxable_amount <= 0:
        return TaxBreakdown.zero()

    # Resolve effective rate
    rate = resolve_gst_rate(tax_category, custom_rate)

    if rate <= 0:
        return TaxBreakdown(
            tax_type=TaxType.GST,
            tax_rate=0.0,
            taxable_amount=round(taxable_amount, 2),
            total_tax=0.0,
            seller_gstin=seller_gstin,
            buyer_gstin=place_of_supply,
        )

    # Determine intra-state vs inter-state
    seller_state = extract_state_code(seller_gstin)
    # place_of_supply can be a state code or a GSTIN
    supply_state = (
        extract_state_code(place_of_supply)
        if len(place_of_supply) > 2
        else place_of_supply
    )
    inter_state = is_inter_state(seller_state, supply_state)

    total_tax = round(taxable_amount * rate / 100, 2)

    if inter_state:
        # Inter-state: full rate as IGST
        return TaxBreakdown(
            tax_type=TaxType.GST,
            tax_rate=rate,
            taxable_amount=round(taxable_amount, 2),
            igst_rate=rate,
            igst_amount=total_tax,
            total_tax=total_tax,
            is_inter_state=True,
            seller_gstin=seller_gstin,
            buyer_gstin=place_of_supply,
        )

    # Intra-state: split equally between CGST and SGST
    half_rate = round(rate / 2, 2)
    cgst = round(taxable_amount * half_rate / 100, 2)
    sgst = total_tax - cgst  # Ensures cgst + sgst == total_tax exactly

    return TaxBreakdown(
        tax_type=TaxType.GST,
        tax_rate=rate,
        taxable_amount=round(taxable_amount, 2),
        cgst_rate=half_rate,
        cgst_amount=cgst,
        sgst_rate=half_rate,
        sgst_amount=sgst,
        total_tax=total_tax,
        is_inter_state=False,
        seller_gstin=seller_gstin,
        buyer_gstin=place_of_supply,
    )


def compute_invoice_tax(
    line_taxable_amounts: list[tuple[float, str]],
    seller_gstin: str = "",
    place_of_supply: str = "",
) -> TaxBreakdown:
    """
    Compute aggregate GST for an entire invoice.

    Args:
        line_taxable_amounts: List of (taxable_amount, tax_category) per line.
        seller_gstin: Seller's GSTIN.
        place_of_supply: Buyer's state code.

    Returns:
        Aggregated TaxBreakdown across all lines.
    """
    total_taxable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_igst = 0.0
    total_tax = 0.0

    seller_state = extract_state_code(seller_gstin)
    supply_state = (
        extract_state_code(place_of_supply)
        if len(place_of_supply) > 2
        else place_of_supply
    )
    inter_state = is_inter_state(seller_state, supply_state)

    for taxable_amount, tax_category in line_taxable_amounts:
        line_tax = compute_line_tax(
            taxable_amount=taxable_amount,
            tax_category=tax_category,
            seller_gstin=seller_gstin,
            place_of_supply=place_of_supply,
        )
        total_taxable += line_tax.taxable_amount
        total_cgst += line_tax.cgst_amount
        total_sgst += line_tax.sgst_amount
        total_igst += line_tax.igst_amount
        total_tax += line_tax.total_tax

    # Use the dominant rate (weighted average is complex; use highest for display)
    dominant_rate = 0.0
    if line_taxable_amounts:
        rates = [resolve_gst_rate(cat) for _, cat in line_taxable_amounts]
        dominant_rate = max(rates) if rates else 0.0

    half_rate = round(dominant_rate / 2, 2) if not inter_state else 0.0

    return TaxBreakdown(
        tax_type=TaxType.GST,
        tax_rate=dominant_rate,
        taxable_amount=round(total_taxable, 2),
        cgst_rate=half_rate,
        cgst_amount=round(total_cgst, 2),
        sgst_rate=half_rate,
        sgst_amount=round(total_sgst, 2),
        igst_rate=dominant_rate if inter_state else 0.0,
        igst_amount=round(total_igst, 2),
        total_tax=round(total_tax, 2),
        is_inter_state=inter_state,
        seller_gstin=seller_gstin,
        buyer_gstin=place_of_supply,
    )
