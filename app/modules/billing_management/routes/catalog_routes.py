"""Catalog routes — CRUD for billable products, services, and plans."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.common.responses import created, deleted, ok, paginated
from app.core.context import OrgContext, get_org_context
from app.core.security.authentications import get_authenticated_identity
from app.db.database import get_database
from app.modules.billing_management.services.catalog_service import CatalogService
from app.modules.gym.schemas import sanitize_payload

router = APIRouter(dependencies=[Depends(get_authenticated_identity)])


def _get_service(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
) -> CatalogService:
    return CatalogService(db, ctx)


@router.post("")
async def create_catalog_item(
    request: Request,
    service: CatalogService = Depends(_get_service),
):
    """Create a new billable catalog item (product, service, or plan)."""
    raw = await request.json()
    data = sanitize_payload(raw)
    document = await service.create_item(data)
    return created(message="Catalog item created successfully.", data=document)


@router.get("")
async def list_catalog_items(
    item_type: str = Query(None, description="Filter by item_type: product, service, subscription_plan"),
    active_only: bool = Query(False),
    app_tag: str = Query(None, description="Filter by app tag"),
    search: str = Query(None, description="Search by name or code"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
    service: CatalogService = Depends(_get_service),
):
    """List catalog items with optional filters."""
    documents, total = await service.list_items(
        item_type=item_type,
        active_only=active_only,
        app_tag=app_tag,
        search=search,
        skip=skip,
        limit=limit,
    )
    return paginated(message="Catalog items retrieved.", data=documents, total=total, skip=skip, limit=limit)


@router.get("/{code}")
async def get_catalog_item(
    code: str,
    service: CatalogService = Depends(_get_service),
):
    """Get a single catalog item by code."""
    document = await service.get_item(code)
    return ok(message="Catalog item retrieved.", data=document)


@router.put("/{code}")
async def update_catalog_item(
    code: str,
    request: Request,
    service: CatalogService = Depends(_get_service),
):
    """Update a catalog item's data fields."""
    raw = await request.json()
    update_data = sanitize_payload(raw)
    document = await service.update_item(code, update_data)
    return ok(message="Catalog item updated successfully.", data=document)


@router.delete("/{code}")
async def delete_catalog_item(
    code: str,
    service: CatalogService = Depends(_get_service),
):
    """Soft-delete a catalog item."""
    await service.delete_item(code)
    return deleted(message="Catalog item deleted successfully.")
