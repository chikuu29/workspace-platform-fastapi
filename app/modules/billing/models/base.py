"""
BillingEntity — abstract base class for all billing domain models.

Every billing document in MongoDB shares the _org + _meta structure
from OrgContext. This base class provides:
 1. Document builder methods (to_document, to_insert_document)
 2. Consistent entity_type tagging
 3. Audit metadata generation delegated to OrgContext

Subclasses define their own `to_data_dict()` — the business payload
stored under the `data` key of each MongoDB document.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


@dataclass
class CustomerRef:
    """
    Flexible customer reference — works with any app's entity.

    Gym passes ref_type="member" + ref_id="M-1",
    Hostel passes ref_type="guest" + ref_id="G-42",
    Future apps pass their own ref_type + ref_id.
    """
    ref_type: str   # "member", "guest", "tenant", "customer"
    ref_id: str     # "M-1", "G-42", etc.
    name: str       # Display name
    email: str = ""
    phone: str = ""
    gstin: str = ""  # Customer's GST number (passed via API)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for MongoDB storage."""
        return {
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "gstin": self.gstin,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CustomerRef:
        """Deserialize from MongoDB document."""
        return cls(
            ref_type=data.get("ref_type", "customer"),
            ref_id=data.get("ref_id", ""),
            name=data.get("name", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            gstin=data.get("gstin", ""),
        )


@dataclass
class TaxBreakdown:
    """
    Itemized tax computation result.

    For intra-state: cgst + sgst = total_tax
    For inter-state: igst = total_tax
    """
    tax_type: str = "gst"           # "gst" | "vat" | "none"
    tax_rate: float = 0.0           # Effective rate (e.g. 18.0)
    taxable_amount: float = 0.0     # Subtotal before tax
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
        """Serialize for MongoDB storage."""
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
    def from_dict(cls, data: Dict[str, Any]) -> TaxBreakdown:
        """Deserialize from MongoDB document."""
        return cls(**{k: data.get(k, v) for k, v in cls.__dataclass_fields__.items()
                      if k in data})

    @classmethod
    def zero(cls) -> TaxBreakdown:
        """No-tax breakdown for exempt items."""
        return cls(tax_type="none", tax_rate=0.0)


class BillingEntity(ABC):
    """
    Abstract base for all billing domain models.

    Subclasses implement to_data_dict() to define their business
    payload. The base class handles _org + _meta structure via
    OrgContext delegation.
    """

    @property
    @abstractmethod
    def entity_type(self) -> str:
        """Return the canonical entity_type string for this model."""
        ...

    @abstractmethod
    def to_data_dict(self) -> Dict[str, Any]:
        """
        Return the business data payload for MongoDB's `data` field.

        This is the mutable, domain-specific content. _org and _meta
        are handled separately by the repository layer.
        """
        ...
