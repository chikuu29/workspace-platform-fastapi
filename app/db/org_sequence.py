"""
Organization-Scoped Sequence Generator.

Generates unique, human-readable IDs scoped to the current organization.
Uses MongoDB atomic `$inc` to guarantee uniqueness even under concurrency.

The key difference from the old sequence.py: org_id and app_id are
automatically pulled from OrgContext — callers never pass them manually.

Usage:
    seq = OrgSequenceService(db, ctx)
    record_id = await seq.monthly("addMember", prefix="GYM")   # GYM-202604-0001
    member_id = await seq.simple("member", prefix="M")          # M-1
"""

from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.context import OrgContext


class OrgSequenceService:
    """
    Atomic sequence generator scoped to the current org + app.

    All counter keys are namespaced by org_id:app_id to prevent
    cross-org sequence collisions.
    """

    COLLECTION = "sequences"

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx

    @property
    def _sequences(self):
        return self._db[self.COLLECTION]

    async def monthly(self, form_id: str, *, prefix: str = "REC") -> str:
        """
        Generate a monthly-reset sequence ID.

        Format: PREFIX-YYYYMM-0001
        Example: GYM-202604-0001

        The counter resets each month automatically because the month
        is part of the counter key.
        """
        current_month = datetime.now(timezone.utc).strftime("%Y%m")
        counter_id = f"{self._ctx.org_name}:{self._ctx.app_code}:{form_id}:{current_month}"

        doc = await self._sequences.find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        # return f"{self._ctx.org_name}_{self._ctx.app_name}_{current_month}-{doc['seq']:04d}"
        return f"{prefix}-{current_month}-{doc['seq']:04d}"

    async def simple(self, entity_type: str, *, prefix: str = "ID") -> str:
        """
        Generate a continuously incrementing sequence ID.

        Format: PREFIX-N
        Example: M-1, M-2, M-3

        Never resets — monotonically increasing per org + app + entity.
        """
        counter_id = f"{self._ctx.org_name}:{self._ctx.app_code}:{entity_type}:continuous"

        doc = await self._sequences.find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        return f"{prefix}-{doc['seq']}"
