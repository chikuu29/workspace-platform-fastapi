"""
Shared Pydantic schemas used across billing API contracts.

These schemas serve two roles:
  1. Internal contracts — app modules use them to send typed data to billing
  2. Response shapes — billing returns them to the frontend for predictable API output
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CustomerRefSchema(BaseModel):
    """
    Customer reference — the app module resolves this from its own data.

    The billing system doesn't know about gym members or hostel guests.
    It receives this generic reference from the calling app module.
    """

    ref_type: str = Field(
        ...,
        description="Entity type from the source app",
        examples=["member", "guest", "tenant", "customer"],
    )
    ref_id: str = Field(
        ...,
        description="Entity ID from the source app",
        examples=["M-1", "G-42"],
    )
    name: str = Field(..., min_length=1, max_length=200)
    email: str = ""
    phone: str = ""
    gstin: str = Field(
        "",
        pattern=r"^$|^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$",
        description="Customer GSTIN (validated format, optional for B2C)",
    )


class TaxBreakdownResponse(BaseModel):
    """
    Tax computation result — server-computed, read-only.

    Included in invoice responses so the frontend can display
    GST breakdown (CGST/SGST or IGST).
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


class AuditInfoResponse(BaseModel):
    """
    Audit metadata included in all billing responses.

    Lets the frontend show who created/updated the document and when.
    """

    record_id: str
    version: int
    created_at: datetime
    created_by: str
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class PaginationResponse(BaseModel):
    """Pagination metadata for list responses."""

    total: int
    skip: int
    limit: int
    has_more: bool


from typing import Generic, List, TypeVar

T = TypeVar("T")


class SuccessEnvelope(BaseModel, Generic[T]):
    """Standard success API response wrapper."""
    success: bool = True
    message: str
    data: T


class PaginatedEnvelope(BaseModel, Generic[T]):
    """Paginated list success API response wrapper."""
    success: bool = True
    message: str
    data: List[T]
    pagination: PaginationResponse
