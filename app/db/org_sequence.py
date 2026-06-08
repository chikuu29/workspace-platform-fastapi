"""
Organization-Scoped Sequence Generator.

Generates unique, human-readable IDs scoped to the current organization.
Uses MongoDB atomic `$inc` to guarantee uniqueness even under concurrency.

The key difference from the old sequence.py: org_id and app_id are
automatically pulled from OrgContext — callers never pass them manually.

ID Format Design (multi-tenant + multi-app safe):
──────────────────────────────────────────────────
    monthly()  → {PREFIX}-{ENTITY_TAG}-{YYYYMM}-{NNNN}
                  e.g. MYGYM-MBR-202605-0001
                       MYGYM-PLN-202605-0001
                       MYGYM-SUB-202605-0001

    The PREFIX is the app-code (scoped per tenant + app).
    The ENTITY_TAG is an abbreviated entity type that ensures
    uniqueness ACROSS entity types within the same app.
    The YYYYMM resets the counter monthly.
    The NNNN is a zero-padded sequence counter.

    This guarantees:
     1. No collisions between entity types (member vs plan vs subscription)
     2. No collisions between orgs (org_id is part of the counter key)
     3. No collisions between apps (app_code is part of the counter key)
     4. Human-readable: you can identify entity type from the ID itself

Usage:
    seq = OrgSequenceService(db, ctx)
    id = await seq.monthly("member", prefix="MYGYM")      # MYGYM-MBR-202605-0001
    id = await seq.monthly("subscription_plan", prefix="MYGYM")  # MYGYM-PLN-202605-0001
    member_id = await seq.simple("member", prefix="M")            # M-1
"""

from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core.context import OrgContext


# ── Entity Tag Map ────────────────────────────────────────────────────────
# Maps entity_type strings to short 3-letter tags for use in record IDs.
# Add new entity types here as the platform grows.
# If an entity type is NOT in this map, the first 3 chars (uppercased)
# are used as a fallback — still unique enough for most cases.

ENTITY_TAG_MAP: dict[str, str] = {
    "member": "MBR",
    "subscription_plan": "PLN",
    "subscription": "SUB",
    "invoice": "INV",
    "payment": "PAY",
    "checkin": "CHK",
    "trainer": "TRN",
    "class": "CLS",
    "appointment": "APT",
    # ── Billing module entity tags ────────────────────────────────────
    "billing_invoice": "INV",
    "billing_payment": "PAY",
    "billing_subscription": "BSB",
    "billing_credit_note": "CRN",
    "billing_tax_profile": "TAX",
    "billing_reminder": "RMD",
    "billing_gateway_config": "GWY",
    "billing_settlement": "STL",
}


def _entity_tag(entity_type: str) -> str:
    """Derive a short tag for embedding in record IDs.

    Looks up the explicit map first; falls back to the first 3 chars
    uppercased for unknown entity types — keeps the system open for
    extension without requiring map updates for every new module.
    """
    return ENTITY_TAG_MAP.get(entity_type, entity_type[:3].upper())


class OrgSequenceService:
    """
    Atomic sequence generator scoped to the current org + app.

    All counter keys are namespaced by org_name:app_code to prevent
    cross-org and cross-app sequence collisions.
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
        Generate a monthly-reset sequence ID with entity-type tag.

        Format: PREFIX-TAG-YYYYMM-0001
        Example: MYGYM-MBR-202605-0001

        The counter resets each month automatically because the month
        is part of the counter key. The entity tag ensures uniqueness
        across different record types within the same org + app.
        """
        current_month = datetime.now(timezone.utc).strftime("%Y%m")
        counter_id = f"{self._ctx.org_name}:{self._ctx.app_code}:{form_id}:{current_month}"

        doc = await self._sequences.find_one_and_update(
            {"_id": counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        tag = _entity_tag(form_id)
        return f"{prefix}-{tag}-{current_month}-{doc['seq']:04d}"

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
