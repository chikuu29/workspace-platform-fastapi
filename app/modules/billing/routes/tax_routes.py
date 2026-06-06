"""Tax routes — tax profile CRUD and GST preview computation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import created, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.core.database import get_db
from app.modules.billing.services.tax_profile_service import TaxProfileService
from app.core.utils import sanitize_payload

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_db),
) -> TaxProfileService:
    return TaxProfileService(db, ctx)


@router.post("/profiles")
async def create_tax_profile(
    request: Request,
    service: TaxProfileService = Depends(_get_service),
):
    """Create a new tax profile (GSTIN registration)."""
    raw = await request.json()
    data = sanitize_payload(raw)
    document = await service.create(data)
    return created(message="Tax profile created successfully.", data=document)


@router.get("/profiles")
async def list_tax_profiles(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: TaxProfileService = Depends(_get_service),
):
    """List all tax profiles for the organization."""
    documents, total = await service.list(skip=skip, limit=limit)
    return paginated(message="Tax profiles retrieved.", data=documents, total=total, skip=skip, limit=limit)


@router.put("/profiles/{gstin}")
async def update_tax_profile(
    gstin: str,
    request: Request,
    service: TaxProfileService = Depends(_get_service),
):
    """Update a tax profile."""
    raw = await request.json()
    update_data = sanitize_payload(raw)
    document = await service.update(gstin, update_data)
    return ok(message="Tax profile updated successfully.", data=document)


@router.post("/calculate")
async def preview_tax(
    request: Request,
):
    """
    Preview GST computation without creating an invoice.

    Expected body:
    {
        "seller_gstin": "29AABCU9603R1ZM",
        "place_of_supply": "27",
        "line_items": [
            { "taxable_amount": 5000, "tax_category": "higher" },
            { "taxable_amount": 2000, "tax_category": "low" }
        ]
    }
    """
    data = await request.json()
    result = TaxProfileService.preview(
        line_items=data.get("line_items", []),
        seller_gstin=data.get("seller_gstin", ""),
        place_of_supply=data.get("place_of_supply", ""),
    )
    return ok(message="Tax computation preview.", data=result)
