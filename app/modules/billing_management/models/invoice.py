"""
Invoice & LineItem — the core billing document.

Invoice numbering follows Indian financial year convention:
    INV/2026-27/0001  (April 2026 – March 2027)

The GSTIN (seller's and buyer's) is passed at invoice-creation time
via the API — not pre-configured in a tax profile. This allows
maximum flexibility for orgs that operate under multiple GSTINs.

CustomerRef is a flexible cross-app reference: Gym member, Hostel
guest, or any future entity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.modules.billing_management.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_PAYMENT_TERMS,
    DiscountType,
    ENTITY_INVOICE,
    InvoiceStatus,
    InvoiceType,
)
from app.modules.billing_management.models.base import (
    BillingEntity,
    CustomerRef,
    TaxBreakdown,
)


@dataclass
class LineItem:
    """
    A single line on an invoice.

    Represents one catalog item × quantity with optional discount.
    Tax is computed per line by the tax engine and stamped here.
    """
    catalog_item_code: str = ""
    description: str = ""
    hsn_sac_code: str = ""
    quantity: float = 1.0
    unit_price: float = 0.0

    # Discount
    discount_type: str = DiscountType.NONE   # percentage | fixed | none
    discount_value: float = 0.0
    discount_amount: float = 0.0             # Computed: actual discount in currency

    # Tax (computed by tax engine)
    tax_category: str = ""
    tax_rate: float = 0.0
    tax_amount: float = 0.0

    # Totals (computed by pricing engine)
    taxable_amount: float = 0.0   # (qty × unit_price) − discount
    line_total: float = 0.0       # taxable_amount + tax_amount

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for MongoDB storage."""
        return {
            "catalog_item_code": self.catalog_item_code,
            "description": self.description,
            "hsn_sac_code": self.hsn_sac_code,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "discount_amount": self.discount_amount,
            "tax_category": self.tax_category,
            "tax_rate": self.tax_rate,
            "tax_amount": self.tax_amount,
            "taxable_amount": self.taxable_amount,
            "line_total": self.line_total,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LineItem:
        """Reconstruct from MongoDB document."""
        return cls(
            catalog_item_code=data.get("catalog_item_code", ""),
            description=data.get("description", ""),
            hsn_sac_code=data.get("hsn_sac_code", ""),
            quantity=float(data.get("quantity", 1.0)),
            unit_price=float(data.get("unit_price", 0.0)),
            discount_type=data.get("discount_type", DiscountType.NONE),
            discount_value=float(data.get("discount_value", 0.0)),
            discount_amount=float(data.get("discount_amount", 0.0)),
            tax_category=data.get("tax_category", ""),
            tax_rate=float(data.get("tax_rate", 0.0)),
            tax_amount=float(data.get("tax_amount", 0.0)),
            taxable_amount=float(data.get("taxable_amount", 0.0)),
            line_total=float(data.get("line_total", 0.0)),
        )


@dataclass
class Invoice(BillingEntity):
    """
    A billing invoice — the central financial document.

    Lifecycle: draft → sent → partial → paid → (void)
    Tax computation is done at creation via the TaxEngine.
    The GSTIN (seller + buyer) is passed at invoice creation time.
    """

    # Identity
    invoice_number: str = ""         # INV/2026-27/0001
    invoice_type: str = InvoiceType.STANDARD

    # Customer (flexible cross-app reference)
    customer_ref: Optional[CustomerRef] = None

    # Line items
    line_items: List[LineItem] = field(default_factory=list)

    # Financials (computed by engines)
    subtotal: float = 0.0            # Sum of line taxable_amounts
    tax_breakdown: Optional[TaxBreakdown] = None
    total: float = 0.0               # subtotal + total_tax
    amount_paid: float = 0.0
    balance_due: float = 0.0
    currency: str = DEFAULT_CURRENCY

    # GST details (passed via API at creation)
    seller_gstin: str = ""           # Org's GSTIN
    buyer_gstin: str = ""            # Customer's GSTIN (if B2B)
    place_of_supply: str = ""        # State code — determines CGST/SGST vs IGST
    is_inter_state: bool = False     # Derived from seller state vs place_of_supply

    # Status & dates
    status: str = InvoiceStatus.DRAFT
    issue_date: str = ""             # ISO format date string
    due_date: str = ""
    payment_terms: str = DEFAULT_PAYMENT_TERMS

    # Source tracking — which app generated this invoice
    source_app: str = ""             # e.g. "myGym", "myHostel"

    # Notes
    notes: str = ""
    terms_and_conditions: str = ""

    @property
    def entity_type(self) -> str:
        return ENTITY_INVOICE

    def to_data_dict(self) -> Dict[str, Any]:
        """Serialize for MongoDB's `data` field."""
        return {
            "invoice_number": self.invoice_number,
            "invoice_type": self.invoice_type,
            "customer_ref": self.customer_ref.to_dict() if self.customer_ref else None,
            "line_items": [item.to_dict() for item in self.line_items],
            "subtotal": self.subtotal,
            "tax_breakdown": self.tax_breakdown.to_dict() if self.tax_breakdown else None,
            "total": self.total,
            "amount_paid": self.amount_paid,
            "balance_due": self.balance_due,
            "currency": self.currency,
            "seller_gstin": self.seller_gstin,
            "buyer_gstin": self.buyer_gstin,
            "place_of_supply": self.place_of_supply,
            "is_inter_state": self.is_inter_state,
            "status": self.status,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "payment_terms": self.payment_terms,
            "source_app": self.source_app,
            "notes": self.notes,
            "terms_and_conditions": self.terms_and_conditions,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Invoice:
        """Reconstruct from MongoDB `data` field."""
        customer_data = data.get("customer_ref")
        tax_data = data.get("tax_breakdown")

        return cls(
            invoice_number=data.get("invoice_number", ""),
            invoice_type=data.get("invoice_type", InvoiceType.STANDARD),
            customer_ref=CustomerRef.from_dict(customer_data) if customer_data else None,
            line_items=[LineItem.from_dict(li) for li in data.get("line_items", [])],
            subtotal=float(data.get("subtotal", 0.0)),
            tax_breakdown=TaxBreakdown.from_dict(tax_data) if tax_data else None,
            total=float(data.get("total", 0.0)),
            amount_paid=float(data.get("amount_paid", 0.0)),
            balance_due=float(data.get("balance_due", 0.0)),
            currency=data.get("currency", DEFAULT_CURRENCY),
            seller_gstin=data.get("seller_gstin", ""),
            buyer_gstin=data.get("buyer_gstin", ""),
            place_of_supply=data.get("place_of_supply", ""),
            is_inter_state=data.get("is_inter_state", False),
            status=data.get("status", InvoiceStatus.DRAFT),
            issue_date=data.get("issue_date", ""),
            due_date=data.get("due_date", ""),
            payment_terms=data.get("payment_terms", DEFAULT_PAYMENT_TERMS),
            source_app=data.get("source_app", ""),
            notes=data.get("notes", ""),
            terms_and_conditions=data.get("terms_and_conditions", ""),
        )
