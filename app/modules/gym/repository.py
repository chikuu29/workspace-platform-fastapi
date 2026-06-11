"""
Gym Repository — Scoped database interface for the Gym module.

Provides semantic methods for member, plan, trainer, subscription, and
attendance entities. Automatically wraps and inherits multi-tenancy filters
and audit metadata from OrgRepository.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.common.org_repository import OrgRepository
from app.core.context import OrgContext
from app.modules.gym.routers.constants import (
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    TRAINER_QUERY,
    ATTENDANCE_QUERY,
    INVOICE_QUERY,
    PAYMENT_QUERY,
    ENTITY_MEMBER,
    ENTITY_PLAN,
    ENTITY_SUBSCRIPTION,
    ENTITY_TRAINER,
    ENTITY_ATTENDANCE,
    _record_query,
    _plan_query,
    _trainer_query,
)


class GymRepository(OrgRepository):
    """
    Unified Gym Repository handling CRUD operations for Gym entities.

    Uses the unified 'records' collection, automatically scoped to the organization.
    """

    def __init__(self, db: AsyncIOMotorDatabase, ctx: OrgContext) -> None:
        """
        Initialize Gym repository.

        Args:
            db: Async Motor Database.
            ctx: Scoped Org Context.
        """
        super().__init__(db, "records", ctx)

    # ── Members ──────────────────────────────────────────────────────────

    async def find_members(self, skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """Find gym members, newest first."""
        return await self.find(
            MEMBER_QUERY,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    async def count_members(self) -> int:
        """Count gym members."""
        return await self.count(MEMBER_QUERY)

    async def get_member(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Retrieve a member by record ID, member ID, or ObjectId."""
        return await self.find_one(_record_query(identifier))

    async def find_duplicate_member(
        self, email: Optional[str], phone: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Find a duplicate member matching email or phone."""
        dup_filters = []
        if email:
            dup_filters.append({"data.email": email})
        if phone:
            dup_filters.append({"data.phone": phone})
        if not dup_filters:
            return None
        return await self.find_one({**MEMBER_QUERY, "$or": dup_filters})

    async def create_member(self, data: Dict[str, Any], prefix: str = "REC") -> Dict[str, Any]:
        """Create a new member document with sequence ID."""
        return await self.insert_one(data, entity_type=ENTITY_MEMBER, prefix=prefix)

    async def update_member(self, identifier: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a member document."""
        return await self.update_one(_record_query(identifier), update_data)

    async def delete_member(self, identifier: str) -> bool:
        """Soft-delete a member."""
        return await self.soft_delete(_record_query(identifier))

    # ── Plans ────────────────────────────────────────────────────────────

    async def find_plans(
        self, active_only: bool = False, skip: int = 0, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List subscription plans."""
        query = {**PLAN_QUERY}
        if active_only:
            query["data.is_active"] = True
        return await self.find(
            query,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    async def count_plans(self, active_only: bool = False) -> int:
        """Count subscription plans."""
        query = {**PLAN_QUERY}
        if active_only:
            query["data.is_active"] = True
        return await self.count(query)

    async def get_plan(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Retrieve a subscription plan by record ID, code, or ObjectId."""
        return await self.find_one({**PLAN_QUERY, **_plan_query(identifier)})

    async def find_plan_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Find plan by code."""
        return await self.find_one({**PLAN_QUERY, "data.code": code})

    async def create_plan(self, data: Dict[str, Any], prefix: str = "REC") -> Dict[str, Any]:
        """Create a subscription plan."""
        return await self.insert_one(data, entity_type=ENTITY_PLAN, prefix=prefix)

    async def update_plan(self, identifier: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a subscription plan."""
        return await self.update_one(
            {**PLAN_QUERY, **_plan_query(identifier)}, update_data
        )

    async def delete_plan(self, identifier: str) -> bool:
        """Soft-delete a subscription plan."""
        return await self.soft_delete({**PLAN_QUERY, **_plan_query(identifier)})

    # ── Trainers ─────────────────────────────────────────────────────────

    async def find_trainers(self, skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
        """List trainers."""
        return await self.find(
            TRAINER_QUERY,
            sort=[("_meta.created.at", -1)],
            skip=skip,
            limit=limit,
        )

    async def count_trainers(self) -> int:
        """Count trainers."""
        return await self.count(TRAINER_QUERY)

    async def get_trainer(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Retrieve a trainer by record ID, trainer ID, or ObjectId."""
        return await self.find_one({**TRAINER_QUERY, **_trainer_query(identifier)})

    async def find_duplicate_trainer(
        self, email: Optional[str], phone: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Find a duplicate trainer matching email or phone."""
        dup_filters = []
        if email:
            dup_filters.append({"data.email": email})
        if phone:
            dup_filters.append({"data.phone": phone})
        if not dup_filters:
            return None
        return await self.find_one({**TRAINER_QUERY, "$or": dup_filters})

    async def create_trainer(self, data: Dict[str, Any], prefix: str = "REC") -> Dict[str, Any]:
        """Create a trainer record."""
        return await self.insert_one(data, entity_type=ENTITY_TRAINER, prefix=prefix)

    async def update_trainer(self, identifier: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a trainer record."""
        return await self.update_one(
            {**TRAINER_QUERY, **_trainer_query(identifier)}, update_data
        )

    async def delete_trainer(self, identifier: str) -> bool:
        """Soft-delete a trainer record."""
        return await self.soft_delete({**TRAINER_QUERY, **_trainer_query(identifier)})

    # ── Subscriptions ────────────────────────────────────────────────────

    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve subscription by subscription_id or id."""
        return await self.find_one({
            **SUBSCRIPTION_QUERY,
            "$or": [
                {"data.subscription_id": subscription_id},
                {"_meta.id": subscription_id},
            ],
        })

    async def find_active_subscription(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Find the active subscription for a member."""
        return await self.find_one({
            **SUBSCRIPTION_QUERY,
            "data.member_id": member_id,
            "data.status": "active",
        })

    async def find_pending_subscription(self, member_id: str, plan_code: str) -> Optional[Dict[str, Any]]:
        """Find a pending subscription for a member + plan combination."""
        return await self.find_one({
            **SUBSCRIPTION_QUERY,
            "data.member_id": member_id,
            "data.plan_code": plan_code,
            "data.status": "pending",
        })

    async def find_subscriptions_by_member(self, member_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """List subscription history for a member."""
        return await self.find(
            {**SUBSCRIPTION_QUERY, "data.member_id": member_id},
            sort=[("_meta.created.at", -1)],
            limit=limit,
        )

    async def create_subscription(self, data: Dict[str, Any], prefix: str = "REC") -> Dict[str, Any]:
        """Create a subscription record."""
        return await self.insert_one(data, entity_type=ENTITY_SUBSCRIPTION, prefix=prefix)

    # ── Attendance ───────────────────────────────────────────────────────

    async def create_attendance(self, data: Dict[str, Any], prefix: str = "REC") -> Dict[str, Any]:
        """Create attendance check-in record."""
        return await self.insert_one(data, entity_type=ENTITY_ATTENDANCE, prefix=prefix)

    async def count_attendance_since(self, start_date: str) -> int:
        """Count daily check-ins since the given date."""
        return await self.count({
            **ATTENDANCE_QUERY,
            "_meta.created.at": {"$gte": start_date},
        })

    async def find_attendance(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Fetch check-ins up to a limit."""
        return await self.find(ATTENDANCE_QUERY, limit=limit)

    async def find_attendance_member_ids_since(self, start_date: str) -> List[str]:
        """Get distinct member IDs that checked in since start_date."""
        return await self.collection.distinct(
            "data.member_id",
            {
                **ATTENDANCE_QUERY,
                "_org.org_id": self._ctx.org_id,
                "data.timestamp": {"$gte": start_date},
            },
        )

    # ── Analytics Aggregations ───────────────────────────────────────────

    async def aggregate_plan_popularity(self) -> List[Dict[str, Any]]:
        """Group active subscriptions by billing_cycle for plan popularity chart.

        Returns chart-ready [{name, value}] sorted by count descending.
        """
        pipeline = [
            {"$match": {
                **self._ctx.active_filter,
                **SUBSCRIPTION_QUERY,
                "data.status": "active",
            }},
            {"$group": {
                "_id": "$data.billing_cycle",
                "count": {"$sum": 1},
            }},
            {"$sort": {"count": -1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=50)

        # Map billing_cycle keys to human-readable labels
        cycle_labels = {
            "monthly": "Monthly",
            "quarterly": "Quarterly",
            "yearly": "Yearly",
        }
        return [
            {
                "name": cycle_labels.get(r["_id"], r["_id"] or "Other"),
                "value": r["count"],
            }
            for r in results
        ]

    async def aggregate_payment_status(self) -> List[Dict[str, Any]]:
        """Group invoices by status for payment status chart.

        Returns chart-ready [{name, value}] with paid/pending/overdue counts.
        """
        pipeline = [
            {"$match": {
                **self._ctx.active_filter,
                **INVOICE_QUERY,
            }},
            {"$group": {
                "_id": "$data.status",
                "count": {"$sum": 1},
            }},
            {"$sort": {"count": -1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=20)

        # Map raw status values to display labels
        status_labels = {
            "paid": "Paid",
            "pending": "Pending",
            "overdue": "Overdue",
            "draft": "Draft",
            "sent": "Sent",
            "cancelled": "Cancelled",
            "partially_paid": "Partially Paid",
        }
        return [
            {
                "name": status_labels.get(r["_id"], r["_id"] or "Unknown"),
                "value": r["count"],
            }
            for r in results
        ]

    async def aggregate_daily_revenue(self, days: int = 30) -> List[Dict[str, Any]]:
        """Aggregate payment amounts by date for the last N days.

        Returns chart-ready [{label, value}] sorted chronologically.
        Uses data.payment_date for grouping and data.amount for summing.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

        pipeline = [
            {"$match": {
                **self._ctx.active_filter,
                **PAYMENT_QUERY,
                "data.status": "captured",
                "data.payment_date": {"$gte": cutoff},
            }},
            {"$group": {
                "_id": "$data.payment_date",
                "total": {"$sum": "$data.amount"},
            }},
            {"$sort": {"_id": 1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=days + 5)

        return [
            {"label": r["_id"], "value": round(r["total"], 2)}
            for r in results
        ]

    async def aggregate_monthly_revenue(self) -> List[Dict[str, Any]]:
        """Aggregate payment amounts by month for the current year.

        Returns chart-ready [{label, value}] with month abbreviations.
        Falls back to parsing data.payment_date string since dates are
        stored as ISO strings, not native BSON dates.
        """
        year_start = datetime.now(timezone.utc).replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%d")

        pipeline = [
            {"$match": {
                **self._ctx.active_filter,
                **PAYMENT_QUERY,
                "data.status": "captured",
                "data.payment_date": {"$gte": year_start},
            }},
            # Extract month from ISO date string "YYYY-MM-DD" → "YYYY-MM"
            {"$addFields": {
                "_month_key": {"$substr": ["$data.payment_date", 0, 7]},
            }},
            {"$group": {
                "_id": "$_month_key",
                "total": {"$sum": "$data.amount"},
            }},
            {"$sort": {"_id": 1}},
        ]
        results = await self.collection.aggregate(pipeline).to_list(length=12)

        month_names = {
            "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
            "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
            "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
        }
        return [
            {
                "label": month_names.get(r["_id"].split("-")[1], r["_id"]),
                "value": round(r["total"], 2),
            }
            for r in results
            if r["_id"]  # guard against None keys
        ]
