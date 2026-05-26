"""
BillingRepository — base repository for billing collections.

Extends OrgRepository for use with dedicated billing collections
(billing_invoices, billing_payments, etc.) instead of the shared
`records` collection.

Inherits all org-scoping, audit stamping, and soft-delete behavior.
Each billing sub-repository instantiates with its own collection name.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.org_repository import OrgRepository
from app.core.context import OrgContext
from app.core.logger import create_logger

logger = create_logger("billing_repository")


class BillingRepository(OrgRepository):
    """
    Base repository for billing collections.

    Usage:
        repo = BillingRepository(db, "billing_invoices", ctx)
        # OR subclass:
        class InvoiceRepository(BillingRepository):
            def __init__(self, db, ctx):
                super().__init__(db, "billing_invoices", ctx)
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        collection_name: str,
        ctx: OrgContext,
    ) -> None:
        super().__init__(db, collection_name, ctx)

    async def find_by_field(
        self,
        field_path: str,
        value: Any,
        *,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a single document by a data field value.

        Convenience method for common lookups like:
            find_by_field("data.invoice_number", "INV/2026-27/0001")
            find_by_field("data.code", "GYM_PRO", entity_type="billing_catalog")
        """
        query: Dict[str, Any] = {field_path: value}
        if entity_type:
            query["_meta.entity_type"] = entity_type
        return await self.find_one(query)

    async def find_by_entity_type(
        self,
        entity_type: str,
        *,
        extra_filter: Optional[Dict[str, Any]] = None,
        sort: Optional[List] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find documents filtered by entity_type within the billing collection."""
        query: Dict[str, Any] = {"_meta.entity_type": entity_type}
        if extra_filter:
            query.update(extra_filter)
        return await self.find(query, sort=sort, skip=skip, limit=limit)

    async def count_by_entity_type(
        self,
        entity_type: str,
        *,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count documents of a specific entity_type."""
        query: Dict[str, Any] = {"_meta.entity_type": entity_type}
        if extra_filter:
            query.update(extra_filter)
        return await self.count(query)

    async def aggregate(
        self,
        pipeline: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Run an aggregation pipeline on the billing collection.

        The caller is responsible for including org-scoping in the
        pipeline's $match stage. Use self._ctx.active_filter for
        the standard org + non-deleted filter.
        """
        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=1000)
