"""
SequenceService — org-scoped, atomic ID generator backed by MongoDB.

Two ID styles are supported:

    include_month=False (default)   →  PREFIX-000001
    include_month=True              →  PREFIX-202606-000001

When include_month=True the sequence counter also resets per-month —
each unique (org, app, entity, YYYYMM) tuple gets its own counter,
preventing cross-month counter drift.
"""

from datetime import datetime, UTC
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.context import OrgContext


class SequenceService:
    COLLECTION = "sequences"

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        self._db = db
        self._ctx = ctx

    @property
    def _sequences(self):
        """Return the Motor collection handle for sequences."""
        return self._db[self.COLLECTION]

    async def _next_sequence(self, sequence_name: str) -> int:
        """
        Atomically increment and return the next sequence value.

        Uses find_one_and_update with upsert so the document is
        created on first use (sequence starts at 1).

        Args:
            sequence_name: Unique key that namespaces this counter.

        Returns:
            The incremented integer value.
        """
        result = await self._sequences.find_one_and_update(
            {"_id": sequence_name},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return result["sequence_value"]

    async def generate_id(
        self,
        entity: str,
        prefix: str,
        pad_length: int = 6,
        include_month: bool = False,
    ) -> str:
        """
        Generate a unique, zero-padded ID for the given entity.

        Args:
            entity:        Logical entity name (e.g. "member", "trainer").
            prefix:        ID prefix string  (e.g. "M", "TR", "SUB").
            pad_length:    Width to zero-pad the counter (default 6).
            include_month: If True, embeds the current YYYYMM segment
                           and resets the counter monthly.

        Returns:
            Formatted ID string. Examples:

                include_month=False → "M-000001"
                include_month=True  → "M-202606-000001"

        Sequence key strategy:
            Without month:  "{org_name}:{app_code}:{entity}"
            With month:     "{org_name}:{app_code}:{entity}:{YYYYMM}"

            Namespacing by org + app ensures cross-org isolation.
            Adding YYYYMM resets the counter at the start of each month.
        """
        month = datetime.now(UTC).strftime("%Y%m")

        if include_month:
            # Monthly-reset counter — counter restarts at 1 each month
            sequence_name = (
                f"{self._ctx.org_name}:{self._ctx.app_code}:{entity}:{month}"
            )
        else:
            # Continuous counter — never resets
            sequence_name = (
                f"{self._ctx.org_name}:{self._ctx.app_code}:{entity}"
            )

        seq = await self._next_sequence(sequence_name)
        padded = str(seq).zfill(pad_length)

        if include_month:
            return f"{prefix}-{month}-{padded}"
        return f"{prefix}-{padded}"
