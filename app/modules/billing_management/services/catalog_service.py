"""
Catalog Service — CRUD + business validation for billable items.

The catalog is app-agnostic: Gym plans, Hostel room charges, and
any future app's products all live in the same billing_catalog
collection, differentiated by app_tags and item_type.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.responses import bad_request, conflict, not_found
from app.core.context import OrgContext
from app.core.logger import create_logger
from app.db.org_sequence import OrgSequenceService
from app.modules.billing_management.constants import ENTITY_CATALOG
from app.modules.billing_management.repositories.catalog_repo import CatalogRepository

logger = create_logger("billing.catalog_service")


class CatalogService:
    """Business logic for catalog item lifecycle."""

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx
        self._repo = CatalogRepository(db, ctx)

    async def create_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new catalog item.

        Validates:
         - name and code are required
         - code is unique within the org
        """
        name = data.get("name", "").strip()
        code = data.get("code", "").strip()

        if not name:
            bad_request(message="Catalog item name is required.")
        if not code:
            bad_request(message="Catalog item code is required.")

        # Duplicate code check (org-scoped)
        existing = await self._repo.find_by_code(code)
        if existing:
            conflict(
                message=f"A catalog item with code '{code}' already exists.",
                error_code="DUPLICATE_CATALOG_CODE",
                details={"existing_record_id": existing["_meta"]["record_id"]},
            )

        # Defaults
        data.setdefault("currency", "INR")
        data.setdefault("is_active", True)
        data.setdefault("item_type", "service")
        data.setdefault("billing_cycle", "one_time")
        data.setdefault("tax_category", "higher")
        data.setdefault("app_tags", [])
        data.setdefault("metadata", {})

        document = await self._repo.insert_one(
            data=data,
            entity_type=ENTITY_CATALOG,
            prefix=self._ctx.app_code.upper(),
        )

        logger.info(
            "Created catalog item code=%s org=%s app=%s",
            code, self._ctx.org_id, self._ctx.app_code,
        )
        return document

    async def list_items(
        self,
        *,
        item_type: Optional[str] = None,
        active_only: bool = False,
        app_tag: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        List catalog items with optional filters.

        Returns (documents, total_count).
        """
        query: Dict[str, Any] = {}
        if item_type:
            query["data.item_type"] = item_type
        if active_only:
            query["data.is_active"] = True
        if app_tag:
            query["$or"] = [
                {"data.app_tags": app_tag},
                {"data.app_tags": {"$size": 0}},
                {"data.app_tags": {"$exists": False}},
            ]
        if search:
            query["$or"] = [
                {"data.name": {"$regex": search, "$options": "i"}},
                {"data.code": {"$regex": search, "$options": "i"}},
            ]

        documents = await self._repo.find(
            query,
            sort=[("data.name", 1)],
            skip=skip,
            limit=limit,
        )
        total = await self._repo.count(query)
        return documents, total

    async def get_item(self, code: str) -> Dict[str, Any]:
        """Get a single catalog item by code."""
        doc = await self._repo.find_by_code(code)
        if not doc:
            not_found(message=f"Catalog item '{code}' not found.")
        return doc

    async def update_item(
        self, code: str, update_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update a catalog item's data fields."""
        if not update_data:
            bad_request(message="No fields provided to update.")

        doc = await self._repo.update_one(
            {"data.code": code},
            update_data,
        )
        if not doc:
            not_found(message=f"Catalog item '{code}' not found.")

        logger.info("Updated catalog item code=%s org=%s", code, self._ctx.org_id)
        return doc

    async def delete_item(self, code: str) -> bool:
        """Soft-delete a catalog item."""
        result = await self._repo.soft_delete({"data.code": code})
        if not result:
            not_found(message=f"Catalog item '{code}' not found.")
        logger.info("Deleted catalog item code=%s org=%s", code, self._ctx.org_id)
        return result
