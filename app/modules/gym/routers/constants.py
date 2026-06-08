"""
gym/routers/constants.py — Shared constants, entity filters, and pure helper functions.

All sub-routers import from here.  This module has NO FastAPI dependencies so it
can never create circular import issues.
"""

from datetime import datetime, timezone
from bson import ObjectId
from dateutil.relativedelta import relativedelta

# ── Entity Type Constants ─────────────────────────────────────────────
# Each value corresponds to _meta.entity_type stored in the MongoDB
# `records` collection.  Used as the discriminator for every query.

ENTITY_MEMBER = "member"
"""Canonical entity type for gym member documents."""

ENTITY_PLAN = "subscription_plan"
"""Canonical entity type for subscription plan templates."""

ENTITY_SUBSCRIPTION = "subscription"
"""Canonical entity type for active member ↔ plan subscription records."""

ENTITY_TRAINER = "trainer"
"""Canonical entity type for gym trainer / staff records."""

ENTITY_ATTENDANCE = "attendance"
"""Canonical entity type for member check-in records."""

# ── Base Query Filters ────────────────────────────────────────────────
# Pre-built dicts used in every MongoDB query to scope results to a
# single entity type.  Always spread with ** when extending.

MEMBER_QUERY = {"_meta.entity_type": ENTITY_MEMBER}
PLAN_QUERY = {"_meta.entity_type": ENTITY_PLAN}
SUBSCRIPTION_QUERY = {"_meta.entity_type": ENTITY_SUBSCRIPTION}
ATTENDANCE_QUERY = {"_meta.entity_type": ENTITY_ATTENDANCE}
TRAINER_QUERY = {"_meta.entity_type": ENTITY_TRAINER}

# ── Allowed Payment Methods ───────────────────────────────────────────
ALLOWED_PAYMENT_METHODS = {"cash", "upi", "card", "net_banking", "bank_transfer"}


# ── Query Builder Helpers ─────────────────────────────────────────────

def _record_query(identifier: str) -> dict:
    """Build a flexible lookup query by id, member_id, or ObjectId.

    Accepts any of the three identifiers so callers never need to know
    which format the client supplied.
    """
    query: dict = {
        "$or": [
            {"_meta.id": identifier},
            {"data.member_id": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


def _plan_query(identifier: str) -> dict:
    """Build a flexible lookup query for plans by id, code, or ObjectId."""
    query: dict = {
        "$or": [
            {"_meta.id": identifier},
            {"data.code": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


def _trainer_query(identifier: str) -> dict:
    """Build a flexible lookup query for trainers by id, trainer_id, or ObjectId."""
    query: dict = {
        "$or": [
            {"_meta.id": identifier},
            {"data.trainer_id": identifier},
        ]
    }
    if ObjectId.is_valid(identifier):
        query["$or"].append({"_id": ObjectId(identifier)})
    return query


# ── Date Arithmetic ───────────────────────────────────────────────────

def _calculate_end_date(start_date: str, billing_cycle: str) -> str:
    """Calculate subscription end date based on billing cycle.

    Uses python-dateutil for accurate month/year arithmetic — handles
    edge cases like Feb 28 → Mar 28 correctly.

    Args:
        start_date:    ISO date string, e.g. "2026-06-01"
        billing_cycle: One of "monthly" | "quarterly" | "yearly"

    Returns:
        ISO date string for the computed end date.
    """
    start = datetime.fromisoformat(start_date)
    cycle_map = {
        "monthly": relativedelta(months=1),
        "quarterly": relativedelta(months=3),
        "yearly": relativedelta(years=1),
    }
    # Default to monthly if an unknown cycle is provided
    delta = cycle_map.get(billing_cycle, relativedelta(months=1))
    return (start + delta).isoformat()
