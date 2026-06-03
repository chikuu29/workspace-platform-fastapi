"""
ReminderDoc — Beanie document for the reminders collection.

Tracks scheduled payment notifications for upcoming, overdue,
and recurring renewal events across all channels.

Inherits auto org-scoping from BillingDocument.
"""

from __future__ import annotations

from typing import List, Optional

from app.core.context import OrgContext
from app.modules.billing.constants import (
    ENTITY_REMINDER,
    ReminderChannel,
    ReminderStatus,
    ReminderType,
)
from app.modules.billing.documents.base import (
    BillingDocument,
    CustomerRefEmbed,
)


class ReminderDoc(BillingDocument):
    """
    Reminder Beanie document — stored in the reminders collection.

    Scheduled notifications for payment-related events.
    Supports multi-channel delivery (email, SMS, WhatsApp, in-app).

    Usage:
        doc = ReminderDoc.create_for_org(ctx, entity_type=ENTITY_REMINDER, ...)
        await doc.insert()

        due = await ReminderDoc.find_due(ctx, "2026-06-01T00:00:00Z")
    """

    # Invoice linkage
    invoice_ref: str = ""

    # Customer (optional — resolved by calling app)
    customer_ref: Optional[CustomerRefEmbed] = None

    # Reminder configuration
    reminder_type: str = ReminderType.UPCOMING
    scheduled_date: str = ""           # ISO datetime
    sent_at: str = ""                  # ISO datetime when actually sent
    channel: str = ReminderChannel.IN_APP

    # Delivery tracking
    status: str = ReminderStatus.SCHEDULED
    attempt_count: int = 0
    max_attempts: int = 3

    # Content
    message_template: str = ""
    notes: str = ""

    class Settings:
        name = "reminders"
        indexes = [
            # Scheduled processing: find due reminders across all orgs
            [("status", 1), ("scheduled_date", 1)],
            # Per-invoice reminders
            [("_org.org_id", 1), ("invoice_ref", 1)],
        ]

    # ── Convenience Finders (all auto org-scoped) ────────────────

    @classmethod
    async def find_due(
        cls, ctx: OrgContext, as_of_date: str
    ) -> List["ReminderDoc"]:
        """Find scheduled reminders that are due for processing."""
        return await cls.org_find(
            ctx,
            {
                "status": ReminderStatus.SCHEDULED,
                "scheduled_date": {"$lte": as_of_date},
            },
            sort=[("scheduled_date", 1)],
            limit=500,
        )
