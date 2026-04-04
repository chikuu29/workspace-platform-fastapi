"""
Organization-Scoped Repository — automatic tenant isolation for MongoDB.

Every query is automatically scoped to the current org via `_org.org_id`.
Every insert automatically stamps `_org` and `_meta` blocks.
Every update automatically tracks `updated.by` and `updated.at`.
Deletes are soft by default (sets `_meta.is_deleted = true`).

This ensures:
 1. Org A can NEVER accidentally read/write Org B's data
 2. Full audit trail on every document (created/updated/deleted by whom)
 3. Zero boilerplate per module — just extend and use

Usage:
    class MemberRepository(OrgRepository):
        def __init__(self, db, ctx: OrgContext):
            super().__init__(db, "records", ctx)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.context import OrgContext
from app.core.logger import create_logger
from app.db.org_sequence import OrgSequenceService

logger = create_logger("org_repository")


class OrgRepository:
    """
    Base repository with automatic org-scoping and audit metadata.

    All read queries include `_org.org_id` filter.
    All writes stamp `_org` + `_meta` blocks.
    Subclass this per-module or use directly for the generic `records` collection.
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        collection_name: str,
        ctx: OrgContext,
    ) -> None:
        self._db = db
        self._collection_name = collection_name
        self._ctx = ctx

    @property
    def collection(self):
        """Lazy collection accessor."""
        return self._db[self._collection_name]

    # ── READ ─────────────────────────────────────────────────────────────

    async def find(
        self,
        query: Optional[Dict[str, Any]] = None,
        *,
        sort: Optional[List] = None,
        skip: int = 0,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Find documents scoped to the current org.

        By default excludes soft-deleted documents. Pass include_deleted=True
        to include them (e.g. for admin/audit views).
        """
        base_filter = self._ctx.org_filter if include_deleted else self._ctx.active_filter
        merged = {**base_filter, **(query or {})}

        cursor = self.collection.find(merged).skip(skip).limit(limit)

        if sort:
            cursor = cursor.sort(sort)

        documents = await cursor.to_list(length=limit)

        # Stringify ObjectId for JSON serialization
        for doc in documents:
            doc["_id"] = str(doc["_id"])

        return documents

    async def find_one(
        self,
        query: Dict[str, Any],
        *,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Find a single document scoped to the current org."""
        base_filter = self._ctx.org_filter if include_deleted else self._ctx.active_filter
        merged = {**base_filter, **query}

        doc = await self.collection.find_one(merged)
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    async def count(
        self,
        query: Optional[Dict[str, Any]] = None,
        *,
        include_deleted: bool = False,
    ) -> int:
        """Count documents scoped to the current org."""
        base_filter = self._ctx.org_filter if include_deleted else self._ctx.active_filter
        merged = {**base_filter, **(query or {})}
        return await self.collection.count_documents(merged)

    # ── WRITE ────────────────────────────────────────────────────────────

    async def insert_one(
        self,
        data: Dict[str, Any],
        *,
        entity_type: str,
        prefix: str = "REC",
    ) -> Dict[str, Any]:
        """
        Insert a document with automatic `_org`, `_meta`, and `record_id`.

        The record_id is auto-generated via OrgSequenceService — callers
        never need to call sequence manually.

        Args:
            data: The business data (stored under the `data` key).
            entity_type: Logical entity type (e.g. "member", "plan", "invoice").
            prefix: Prefix for the auto-generated record_id (e.g. "GYM" → GYM-202604-0001).

        Returns:
            The inserted document with stringified _id and generated record_id.
        """
        # Auto-generate record_id — no manual call needed
        seq = OrgSequenceService(self._db, self._ctx)
        record_id = await seq.monthly(entity_type, prefix=prefix)

        document = {
            "_org": self._ctx.to_org_block(),
            "_meta": self._ctx.to_created_meta(entity_type, record_id),
            "data": data,
        }

        result = await self.collection.insert_one(document)

        document["_id"] = str(result.inserted_id)

        logger.info(
            "Inserted %s record_id=%s org=%s by=%s",
            entity_type,
            record_id,
            self._ctx.org_id,
            self._ctx.user_id,
        )

        return document

    # ── UPDATE ───────────────────────────────────────────────────────────

    async def update_one(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Update a document's `data` field with automatic audit stamping.

        Scoped to org. Increments `_meta.version`, sets `updated.at/by`.
        Returns the updated document or None if not found.
        """
        merged_filter = {**self._ctx.active_filter, **query}

        update_payload = {
            "$set": {
                **{f"data.{k}": v for k, v in update_data.items()},
                **self._ctx.to_update_meta(),
            },
            "$inc": {"_meta.version": 1},
        }

        doc = await self.collection.find_one_and_update(
            merged_filter,
            update_payload,
            return_document=ReturnDocument.AFTER,
        )

        if doc:
            doc["_id"] = str(doc["_id"])
            logger.info(
                "Updated record org=%s by=%s",
                self._ctx.org_id,
                self._ctx.user_id,
            )

        return doc

    # ── DELETE (soft) ────────────────────────────────────────────────────

    async def soft_delete(
        self,
        query: Dict[str, Any],
    ) -> bool:
        """
        Soft-delete a document: sets `_meta.is_deleted = true` with audit.

        Returns True if a document was marked as deleted, False if not found.
        """
        merged_filter = {**self._ctx.active_filter, **query}

        result = await self.collection.update_one(
            merged_filter,
            {
                "$set": self._ctx.to_delete_meta(),
                "$inc": {"_meta.version": 1},
            },
        )

        if result.modified_count > 0:
            logger.info(
                "Soft-deleted record org=%s by=%s",
                self._ctx.org_id,
                self._ctx.user_id,
            )
            return True

        return False

    # ── HARD DELETE (use sparingly) ──────────────────────────────────────

    async def hard_delete(
        self,
        query: Dict[str, Any],
    ) -> bool:
        """
        Permanently remove a document. Use soft_delete unless you have a
        specific reason (e.g. GDPR data erasure).
        """
        merged_filter = {**self._ctx.org_filter, **query}
        result = await self.collection.delete_one(merged_filter)

        if result.deleted_count > 0:
            logger.warning(
                "Hard-deleted record org=%s by=%s",
                self._ctx.org_id,
                self._ctx.user_id,
            )
            return True

        return False
