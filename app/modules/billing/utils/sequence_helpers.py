"""
Billing Sequence Helpers — shared number generation utilities.

Extracts the duplicated sequence logic from InvoiceService and
PaymentService into a single reusable module.

All billing numbers follow the Indian Financial Year format:
  {prefix}/{FY}/{counter:04d}
  Example: INV/2026-27/0001, PAY/2026-27/0003, ORD/2026-27/0042

Counter keys are namespaced by org + app + entity + FY to prevent
cross-org and cross-entity collisions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.context import OrgContext
from app.db.org_sequence import OrgSequenceService


def indian_financial_year() -> str:
    """
    Derive the Indian financial year string for billing numbering.

    Indian FY runs April → March:
      May 2026 → "2026-27"
      Feb 2027 → "2026-27"
      Apr 2027 → "2027-28"

    Returns:
        Financial year string like "2026-27".
    """
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month

    if month >= 4:
        # April onwards → current year to next year
        return f"{year}-{str(year + 1)[-2:]}"
    else:
        # Jan-Mar → previous year to current year
        return f"{year - 1}-{str(year)[-2:]}"


async def generate_billing_number(
    db: AsyncIOMotorDatabase,
    ctx: OrgContext,
    *,
    prefix: str,
    entity_key: str,
) -> str:
    """
    Atomic billing number generator.

    Format: {prefix}/{FY}/{counter:04d}
    Examples: INV/2026-27/0001, PAY/2026-27/0003, CN/2026-27/0001

    Counter is org-scoped and FY-scoped — resets each financial year.
    Uses MongoDB $inc for atomic, collision-free counter generation.

    Args:
        db: Motor database instance.
        ctx: Current org context (from JWT + headers).
        prefix: Number prefix (e.g., 'INV', 'PAY', 'ORD').
        entity_key: Entity identifier for counter isolation
            (e.g., 'invoice', 'payment', 'order').

    Returns:
        Formatted billing number string like "INV/2026-27/0001".
    """
    fy = indian_financial_year()
    seq = OrgSequenceService(db, ctx)
    counter_id = f"{entity_key}:{fy}"

    doc = await seq._sequences.find_one_and_update(
        {"_id": f"{ctx.org_name}:{ctx.app_code}:{counter_id}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )

    return f"{prefix}/{fy}/{doc['seq']:04d}"
