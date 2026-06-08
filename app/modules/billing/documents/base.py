"""
BillingDocument — Beanie base with automatic org-scoping.

Every find/find_one/count query is automatically scoped to the
current org_id. The caller NEVER writes org_id filters manually.

Replaces OrgRepository + BillingRepository for the billing module.
Org isolation, audit trails, versioning, and soft-delete are all
built into the base class methods.

Usage:
    # All queries auto-scoped — zero manual filtering:
    invoices = await InvoiceDoc.org_find(ctx, {"status": "draft"})
    invoice  = await InvoiceDoc.org_find_one(ctx, {"invoice_number": "INV/2026-27/0001"})
    count    = await InvoiceDoc.org_count(ctx, {"status": "paid"})

    # Insert auto-stamps _org + _meta:
    doc = InvoiceDoc.create_for_org(ctx, entity_type="...", id="...", **fields)
    await doc.insert()

    # Update auto-stamps audit trail:
    doc.status = "paid"
    await doc.org_save(ctx)

    # Soft-delete with audit:
    await doc.org_soft_delete(ctx)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar

from beanie import Document, Insert, before_event
from pydantic import BaseModel, Field

from app.core.context import OrgContext
from app.core.logger import create_logger

logger = create_logger("billing.document")


# ── Embedded Sub-Models ──────────────────────────────────────────────


class OrgBlock(BaseModel):
    """
    Organization context — immutable after insert.

    Populated from OrgContext (JWT + headers) at document creation.
    Used for tenant isolation — every query filters by org_id.
    """

    org_id: int
    org_uuid: str = ""
    org_name: str = ""
    app_code: str = ""
    app_name: str = ""


class AuditStamp(BaseModel):
    """Who performed the action and when."""

    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by: str = ""


class MetaBlock(BaseModel):
    """
    Document metadata — system-managed audit trail.

    Mirrors the _meta block from OrgRepository but as a typed model.
    Version increments on every mutation. Soft-delete sets is_deleted.
    """

    entity_type: str = ""
    id: str = ""
    version: int = 1
    is_deleted: bool = False
    created: AuditStamp = Field(default_factory=AuditStamp)
    updated: Optional[AuditStamp] = None
    deleted: Optional[AuditStamp] = None


# ── Shared Embedded Sub-Models ───────────────────────────────────────
# Placed here so every document can import from a single location.


class CustomerRefEmbed(BaseModel):
    """
    Flexible customer reference — works with any app's entity.

    The calling app resolves the customer from its own data
    (gym member, hostel guest, etc.) and passes this reference.
    """

    ref_type: str = "customer"
    ref_id: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    gstin: str = ""


# ── Base Billing Document ────────────────────────────────────────────

T = TypeVar("T", bound="BillingDocument")


class BillingDocument(Document):
    """
    Base Beanie document with AUTOMATIC org-scoping on every query.

    Design rationale:
    - org_find / org_find_one / org_count inject the org_id filter
      so callers never forget tenant isolation.
    - create_for_org stamps _org + _meta from OrgContext automatically.
    - org_save / org_soft_delete handle audit trails on mutations.

    Subclasses only define their business fields and Settings.name.
    """

    # The alias matches MongoDB field names (_org, _meta)
    org: OrgBlock = Field(alias="_org")
    meta_info: MetaBlock = Field(alias="_meta")

    class Settings:
        name = "billing_base"
        use_state_management = True

    # ── Factory: Build a document pre-stamped for an org ──────────

    @classmethod
    def create_for_org(
        cls: type[T],
        ctx: OrgContext,
        *,
        entity_type: str,
        id: str,
        **kwargs: Any,
    ) -> T:
        """
        Build a new document with _org and _meta auto-populated.

        The calling service only provides business fields via kwargs.
        _org block comes from OrgContext (JWT), _meta is initialized
        with creation audit stamp.

        Args:
            ctx: Current request's org context (from JWT + headers).
            entity_type: Logical entity type (e.g. "invoice").
            id: Auto-generated record ID (from OrgSequenceService).
            **kwargs: Business fields for the document subclass.

        Returns:
            A new document instance ready for .insert().
        """
        return cls(
            **{
                "_org": OrgBlock(
                    org_id=ctx.org_id,
                    org_uuid=ctx.org_uuid,
                    org_name=ctx.org_name,
                    app_code=ctx.app_code,
                    app_name=ctx.app_name,
                ),
                "_meta": MetaBlock(
                    entity_type=entity_type,
                    id=id,
                    created=AuditStamp(by=ctx.user_id),
                ),
                **kwargs,
            },
        )

    # ── Org-scoped filter (injected into every query) ────────────

    @classmethod
    def _org_filter(cls, ctx: OrgContext) -> Dict[str, Any]:
        """
        Base org-scoping filter — automatically excludes soft-deleted docs.

        Every org_find / org_find_one / org_count call merges this
        filter with the caller's query. This ensures:
        1. Org A can NEVER read Org B's data
        2. Soft-deleted documents are excluded by default
        """
        return {
            "_org.org_id": ctx.org_id,
            "_meta.is_deleted": False,
        }

    # ── Auto-scoped Read Queries ─────────────────────────────────

    @classmethod
    async def org_find(
        cls: type[T],
        ctx: OrgContext,
        query: Optional[Dict[str, Any]] = None,
        *,
        sort: Optional[List] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[T]:
        """
        Find documents — automatically scoped to current org.

        Args:
            ctx: Current request's org context.
            query: Additional filters (e.g. {"status": "draft"}).
            sort: Sort specification (e.g. [("issue_date", -1)]).
            skip: Pagination offset.
            limit: Max documents to return.

        Returns:
            List of typed document instances.
        """
        merged = {**cls._org_filter(ctx), **(query or {})}
        find_query = cls.find(merged).skip(skip).limit(limit)
        if sort:
            find_query = find_query.sort(sort)
        return await find_query.to_list()

    @classmethod
    async def org_find_one(
        cls: type[T],
        ctx: OrgContext,
        query: Optional[Dict[str, Any]] = None,
    ) -> Optional[T]:
        """
        Find a single document — automatically scoped to current org.

        Returns None if not found (never raises).
        """
        merged = {**cls._org_filter(ctx), **(query or {})}
        return await cls.find_one(merged)

    @classmethod
    async def org_count(
        cls,
        ctx: OrgContext,
        query: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count documents — automatically scoped to current org."""
        merged = {**cls._org_filter(ctx), **(query or {})}
        return await cls.find(merged).count()

    # ── Org-scoped Mutations ─────────────────────────────────────

    async def org_save(self, ctx: OrgContext) -> None:
        """
        Save with automatic audit stamping + version increment.

        Call this instead of bare .save() to ensure the audit trail
        is maintained. The caller just mutates fields and calls org_save.
        """
        self.meta_info.updated = AuditStamp(by=ctx.user_id)
        self.meta_info.version += 1
        await self.save()
        logger.info(
            "Updated %s id=%s org=%s by=%s",
            self.meta_info.entity_type,
            self.meta_info.id,
            self.org.org_id,
            ctx.user_id,
        )

    async def org_soft_delete(self, ctx: OrgContext) -> None:
        """
        Soft-delete with audit trail.

        Sets is_deleted=True and stamps who deleted and when.
        The document remains in MongoDB but is excluded from all
        org_find / org_find_one / org_count queries.
        """
        self.meta_info.is_deleted = True
        self.meta_info.deleted = AuditStamp(by=ctx.user_id)
        self.meta_info.version += 1
        await self.save()
        logger.info(
            "Soft-deleted %s id=%s org=%s by=%s",
            self.meta_info.entity_type,
            self.meta_info.id,
            self.org.org_id,
            ctx.user_id,
        )

    # ── Beanie Lifecycle Hooks ───────────────────────────────────

    @before_event(Insert)
    def _stamp_created(self) -> None:
        """Ensure creation timestamp is set on insert."""
        if not self.meta_info.created.at:
            self.meta_info.created.at = datetime.now(timezone.utc)
        self.meta_info.version = 1
