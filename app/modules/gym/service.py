"""
Gym Service — Central business logic orchestrator for Gym operations.

Integrates GymRepository and SequenceService to perform business workflows
for members, plans, trainers, attendance, and analytics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.context import OrgContext
from app.services.sequence_service import SequenceService
from app.modules.gym.repository import GymRepository
from app.common.responses import conflict, not_found, bad_request
from app.modules.gym.routers.constants import (
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    TRAINER_QUERY,
    ATTENDANCE_QUERY,
)

logger = logging.getLogger("app.gym.service")


class GymService:
    """
    Encapsulates core business logic for the Gym module.
    """

    def __init__(
        self,
        repository: GymRepository,
        db: AsyncIOMotorDatabase,
        ctx: OrgContext,
    ) -> None:
        """
        Initialize Gym Service.

        Args:
            repository: Gym-specific repository.
            db: Motor async database.
            ctx: OrgContext.
        """
        self.repository = repository
        self._db = db
        self._ctx = ctx

    # ── Private Helpers ───────────────────────────────────────────────────

    async def _enrich_member(self, member: dict) -> dict:
        """
        Attach subscription summary and compute dynamic status.
        """
        member_id = member["data"].get("member_id")
        if not member_id:
            member["subscription"] = None
            member["has_plan"] = False
            member["data"]["status"] = "frozen"
            return member

        sub_doc = await self.repository.find_active_subscription(member_id)
        print(f"sub_doc",sub_doc)
        if sub_doc:
            sub = sub_doc["data"]
            member["subscription"] = {
                "subscription_id": sub.get("subscription_id"),
                "plan_name": sub.get("plan_name"),
                "plan_code": sub.get("plan_code"),
                "price": sub.get("price", 0),
                "currency": sub.get("currency", "INR"),
                "billing_cycle": sub.get("billing_cycle"),
                "start_date": sub.get("start_date"),
                "end_date": sub.get("end_date"),
                "status": sub.get("status"),
                "is_paid": sub.get("is_paid", False),
            }
            member["has_plan"] = True

            # ── Dynamic status calculation ────────────────────────────────
            now = datetime.now(timezone.utc)
            end_date_str = sub.get("end_date")
            is_paid = sub.get("is_paid", False)

            if end_date_str:
                try:
                    end_date = datetime.fromisoformat(end_date_str)
                    if end_date.tzinfo is None:
                      end_date = end_date.replace(tzinfo=timezone.utc)

                    days_remaining = (end_date - now).days

                    if days_remaining < 0:
                        member["data"]["status"] = "frozen"
                    elif not is_paid:
                        member["data"]["status"] = "attention"
                    elif days_remaining <= 7:
                        member["data"]["status"] = "attention"
                    else:
                        member["data"]["status"] = "active"
                except (ValueError, TypeError):
                    member["data"]["status"] = "attention"
            else:
                member["data"]["status"] = "attention" if not is_paid else "active"
        else:
            member["subscription"] = None
            member["has_plan"] = False
            member["data"]["status"] = "frozen"

        return member

    # ── Members ──────────────────────────────────────────────────────────

    async def add_member(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new gym member.
        """
        logger.info(
            f"Initiating new gym member addition by user={self._ctx.user_id} in org={self._ctx.org_id}"
        )
        email = data.get("email")
        phone = data.get("phone")

        existing = await self.repository.find_duplicate_member(email, phone)
        if existing:
            conflict(
                message="A member with this email or phone already exists.",
                error_code="DUPLICATE_MEMBER",
                details={
                    "existing_member_id": existing["data"].get("member_id"),
                    "existing_id": existing["_meta"]["id"],
                },
            )

        try:
            seq = SequenceService(self._db, self._ctx)
            member_id = await seq.generate_id(
                entity="member", prefix="M", pad_length=1, include_month=False
            )
            data["member_id"] = member_id

            document = await self.repository.create_member(
                data=data,
                prefix=self._ctx.app_code.upper(),
            )
            return {
                "id": document["_meta"]["id"],
                "member_id": member_id,
            }
        except Exception as e:
            logger.error(f"Failed to register gym member: {e}", exc_info=True)
            raise


    async def list_members(self, skip: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """
        List members with active subscription summaries.
        """
        documents = await self.repository.find_members(skip=skip, limit=limit)
        total = await self.repository.count_members()

        enriched = [await self._enrich_member(doc) for doc in documents]
        return enriched, total

    async def get_member_detail(self, identifier: str) -> Dict[str, Any]:
        """
        Get single member with subscription + plan details.
        """
        doc = await self.repository.get_member(identifier)
        if not doc:
            not_found(message=f"Member '{identifier}' not found.")

       
        doc = await self._enrich_member(doc)

        member_id = doc["data"].get("member_id")
        if member_id and doc.get("subscription"):
            plan_code = doc["subscription"].get("plan_code")
            if plan_code:
                plan_doc = await self.repository.find_plan_by_code(plan_code)
                doc["plan_details"] = plan_doc["data"] if plan_doc else None
            else:
                doc["plan_details"] = None
        else:
            doc["plan_details"] = None

        if member_id:
            all_subs = await self.repository.find_subscriptions_by_member(member_id, limit=20)
            doc["subscription_history"] = [
                {
                    "subscription_id": s["data"].get("subscription_id"),
                    "plan_name": s["data"].get("plan_name"),
                    "status": s["data"].get("status"),
                    "start_date": s["data"].get("start_date"),
                    "end_date": s["data"].get("end_date"),
                    "price": s["data"].get("price", 0),
                    "is_paid": s["data"].get("is_paid", False),
                }
                for s in all_subs
            ]
        else:
            doc["subscription_history"] = []

        return doc

    async def update_member(self, identifier: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update member fields.
        """
        try:
            doc = await self.repository.update_member(identifier, update_data)
            if not doc:
                not_found(message=f"Member '{identifier}' not found.")
            return doc
        except Exception as e:
            logger.error(f"Failed to update gym member {identifier}: {e}", exc_info=True)
            raise

    async def delete_member(self, identifier: str) -> None:
        """
        Soft-delete a member.
        """
        try:
            result = await self.repository.delete_member(identifier)
            if not result:
                not_found(message=f"Member '{identifier}' not found.")
        except Exception as e:
            logger.error(f"Failed to soft-delete gym member {identifier}: {e}", exc_info=True)
            raise


    # ── Plans ────────────────────────────────────────────────────────────

    async def create_plan(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a subscription plan.
        """
        if not data.get("name"):
            bad_request(message="Plan name is required.")
        if not data.get("code"):
            bad_request(message="Plan code is required.")

        existing = await self.repository.find_plan_by_code(data["code"])
        if existing:
            conflict(
                message=f"A plan with code '{data['code']}' already exists.",
                error_code="DUPLICATE_PLAN_CODE",
                details={"existing_id": existing["_meta"]["id"]},
            )

        data.setdefault("currency", "INR")
        data.setdefault("billing_cycle", "monthly")
        data.setdefault("is_active", True)
        data.setdefault("features", [])
        data.setdefault("accent_color", "blue")

        try:
            document = await self.repository.create_plan(
                data=data,
                prefix=self._ctx.app_code.upper(),
            )
            return document
        except Exception as e:
            logger.error(f"Failed to create subscription plan: {e}", exc_info=True)
            raise

    async def list_plans(
        self, active_only: bool = False, skip: int = 0, limit: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List plans.
        """
        documents = await self.repository.find_plans(active_only=active_only, skip=skip, limit=limit)
        total = await self.repository.count_plans(active_only=active_only)
        return documents, total

    async def get_plan(self, identifier: str) -> Dict[str, Any]:
        """
        Get plan detail.
        """
        doc = await self.repository.get_plan(identifier)
        if not doc:
            not_found(message=f"Subscription plan '{identifier}' not found.")
        return doc

    async def update_plan(self, identifier: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update plan fields.
        """
        try:
            doc = await self.repository.update_plan(identifier, update_data)
            if not doc:
                not_found(message=f"Subscription plan '{identifier}' not found.")
            return doc
        except Exception as e:
            logger.error(f"Failed to update subscription plan {identifier}: {e}", exc_info=True)
            raise

    async def delete_plan(self, identifier: str) -> None:
        """
        Soft-delete a plan.
        """
        try:
            result = await self.repository.delete_plan(identifier)
            if not result:
                not_found(message=f"Subscription plan '{identifier}' not found.")
        except Exception as e:
            logger.error(f"Failed to soft-delete subscription plan {identifier}: {e}", exc_info=True)
            raise


    # ── Trainers ─────────────────────────────────────────────────────────

    async def add_trainer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Onboard a trainer.
        """
        email = data.get("email")
        phone = data.get("phone")

        existing = await self.repository.find_duplicate_trainer(email, phone)
        if existing:
            conflict(
                message="A trainer with this email or phone already exists.",
                error_code="DUPLICATE_TRAINER",
            )

        try:
            seq = SequenceService(self._db, self._ctx)
            trainer_id = await seq.generate_id(
                entity="trainer", prefix="TR", pad_length=1, include_month=False
            )
            data["trainer_id"] = trainer_id

            document = await self.repository.create_trainer(
                data=data,
                prefix=self._ctx.app_code.upper(),
            )
            return {
                "id": document["_meta"]["id"],
                "trainer_id": trainer_id,
            }
        except Exception as e:
            logger.error(f"Failed to onboard trainer: {e}", exc_info=True)
            raise

    async def list_trainers(self, skip: int = 0, limit: int = 50) -> Tuple[List[Dict[str, Any]], int]:
        """
        List trainers.
        """
        docs = await self.repository.find_trainers(skip=skip, limit=limit)
        total = await self.repository.count_trainers()
        return docs, total

    async def get_trainer(self, identifier: str) -> Dict[str, Any]:
        """
        Get trainer detail.
        """
        doc = await self.repository.get_trainer(identifier)
        if not doc:
            not_found(message=f"Trainer '{identifier}' not found.")
        return doc

    async def update_trainer(self, identifier: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update trainer fields.
        """
        try:
            doc = await self.repository.update_trainer(identifier, update_data)
            if not doc:
                not_found(message=f"Trainer '{identifier}' not found.")
            return doc
        except Exception as e:
            logger.error(f"Failed to update trainer {identifier}: {e}", exc_info=True)
            raise

    async def delete_trainer(self, identifier: str) -> None:
        """
        Soft-delete a trainer.
        """
        try:
            result = await self.repository.delete_trainer(identifier)
            if not result:
                not_found(message=f"Trainer '{identifier}' not found.")
        except Exception as e:
            logger.error(f"Failed to soft-delete trainer {identifier}: {e}", exc_info=True)
            raise


    # ── Attendance ───────────────────────────────────────────────────────

    async def member_checkin(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record a check-in event.
        """
        member_id = data.get("member_id")
        if not member_id:
            bad_request(message="member_id is required.")

        member_doc = await self.repository.get_member(member_id)
        if not member_doc:
            not_found(message=f"Member {member_id} not found.")

        sub = await self.repository.find_active_subscription(member_id)

        now = datetime.now(timezone.utc)
        checkin_data = {
            "member_id": member_id,
            "member_name": (
                f"{member_doc['data'].get('firstName', '')} "
                f"{member_doc['data'].get('lastName', '')}"
            ).strip(),
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "hour": now.hour,
            "subscription_id": sub["data"]["subscription_id"] if sub else None,
            "has_active_plan": bool(sub),
        }

        try:
            doc = await self.repository.create_attendance(
                data=checkin_data,
                prefix=self._ctx.app_code.upper(),
            )
            return doc
        except Exception as e:
            logger.error(f"Failed to record member check-in: {e}", exc_info=True)
            raise


    # ── Analytics ────────────────────────────────────────────────────────

    async def get_kpis(self) -> Dict[str, Any]:
        """Retrieve dashboard KPIs and recent enrollments.

        Optimised: no N+1 subscription lookups for recent members.
        Returns scalar counts + a lightweight recent-members list.
        """
        total = await self.repository.count_members()
        active = await self.repository.count({**MEMBER_QUERY, "data.status": "active"})
        attention = await self.repository.count({**MEMBER_QUERY, "data.status": "attention"})
        frozen = await self.repository.count({**MEMBER_QUERY, "data.status": "frozen"})

        now = datetime.now(timezone.utc)
        month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        added_this_month = await self.repository.count({
            **MEMBER_QUERY,
            "_meta.created.at": {"$gte": month_start},
        })

        # Revenue MRR from active subscriptions
        revenue_pipeline = [
            {"$match": {**self._ctx.active_filter, **SUBSCRIPTION_QUERY, "data.status": "active"}},
            {"$group": {"_id": None, "total": {"$sum": "$data.price"}}},
        ]
        revenue_result = await self.repository.collection.aggregate(revenue_pipeline).to_list(length=1)
        revenue_mrr = revenue_result[0]["total"] if revenue_result else 0

        # Today's check-ins
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        checkins_today = await self.repository.count_attendance_since(today_start)

        # Trainers
        total_trainers = await self.repository.count_trainers()
        active_trainers = await self.repository.count({**TRAINER_QUERY, "data.status": "active"})
        trainer_utilization = (
            round(active_trainers / total_trainers * 100) if total_trainers > 0 else 0
        )

        # Recent members — lightweight, no subscription enrichment
        recent_docs = await self.repository.find(
            MEMBER_QUERY,
            sort=[("_meta.created.at", -1)],
            limit=5,
        )
        recent_members = [
            {
                "id": d["_meta"]["id"],
                "member_id": d["data"].get("member_id", "N/A"),
                "name": (
                    f"{d['data'].get('firstName', '')} "
                    f"{d['data'].get('lastName', '')}"
                ).strip() or "Unknown",
                "plan": d["data"].get("plan", "N/A"),
                "created_at": d["_meta"]["created"]["at"],
                "status": d["data"].get("status", "active"),
            }
            for d in recent_docs
        ]

        return {
            "kpis": {
                "total_members": total,
                "active_members": active,
                "attention_members": attention,
                "frozen_members": frozen,
                "members_added_this_month": added_this_month,
                "total_trainers": total_trainers,
                "revenue_mrr": revenue_mrr,
                "checkins_today": checkins_today,
                "trainer_utilization": trainer_utilization,
            },
            "recent_members": recent_members,
        }

    # ── Widget Analytics Engine ──────────────────────────────────────────
    #
    # Registry-based analytics: each widget name maps to a handler method
    # that returns a self-describing envelope with chart_type + series data.
    # The frontend ChartCard auto-configures rendering from the response.
    #
    # Adding a new widget = 1 handler method + 1 registry entry. Zero routes.
    # ─────────────────────────────────────────────────────────────────────

    WIDGET_REGISTRY: Dict[str, str] = {
        "revenue_trend": "_widget_revenue_trend",
        "attendance_trend": "_widget_attendance_trend",
        "membership_distribution": "_widget_membership_distribution",
        "plan_popularity": "_widget_plan_popularity",
        "payment_status": "_widget_payment_status",
    }

    async def get_widget_data(self, widget_name: str, params: Dict[str, str]) -> Any:
        """Dispatch to the registered widget handler and optionally reshape.

        Args:
            widget_name: Key from WIDGET_REGISTRY.
            params: Query params dict (includes optional chart_type override).

        Returns:
            Widget envelope dict or None if widget not found.
        """
        method_name = self.WIDGET_REGISTRY.get(widget_name)
        if not method_name:
            return None

        handler = getattr(self, method_name)
        result = await handler(params)

        # Frontend chart_type override — reshape data if requested type differs
        requested_type = params.get("chart_type")
        if requested_type and requested_type != result.get("chart_type"):
            result = self._reshape_widget(result, requested_type)

        return result

    # ── Widget Handlers ──────────────────────────────────────────────────

    async def _widget_revenue_trend(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Revenue trend widget — line chart with range filter."""
        range_val = params.get("range", "30d")

        if range_val == "year":
            series = await self.repository.aggregate_monthly_revenue()
            subtitle = "Monthly income this year"
        else:
            series = await self.repository.aggregate_daily_revenue(days=30)
            subtitle = "Daily income over the last 30 days"

        return {
            "widget": "revenue_trend",
            "chart_type": "line",
            "title": "Revenue Trend",
            "subtitle": subtitle,
            "filters": [
                {"label": "Last 30 Days", "value": "30d"},
                {"label": "This Year", "value": "year"},
            ],
            "series": series,
        }

    async def _widget_attendance_trend(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Attendance trend widget — line chart of daily visits."""
        days = int(params.get("days", "7"))
        now = datetime.now(timezone.utc)
        dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

        daily_visits = []
        for d in reversed(dates):
            count = await self.repository.count({**ATTENDANCE_QUERY, "data.date": d})
            daily_visits.append({"label": d, "value": count})

        return {
            "widget": "attendance_trend",
            "chart_type": "line",
            "title": "Attendance Trend",
            "subtitle": f"Daily visits for the last {days} days",
            "series": daily_visits,
        }

    async def _widget_membership_distribution(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Membership distribution widget — pie chart of member statuses."""
        active = await self.repository.count({**MEMBER_QUERY, "data.status": "active"})
        frozen = await self.repository.count({**MEMBER_QUERY, "data.status": "frozen"})
        attention = await self.repository.count({**MEMBER_QUERY, "data.status": "attention"})

        return {
            "widget": "membership_distribution",
            "chart_type": "pie",
            "title": "Membership Distribution",
            "subtitle": "Active, frozen, and attention memberships",
            "series": [
                {"name": "Active Members", "value": active},
                {"name": "Frozen Members", "value": frozen},
                {"name": "Needs Attention", "value": attention},
            ],
        }

    async def _widget_plan_popularity(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Plan popularity widget — pie chart of subscription billing cycles."""
        series = await self.repository.aggregate_plan_popularity()

        return {
            "widget": "plan_popularity",
            "chart_type": "pie",
            "title": "Plan Popularity",
            "subtitle": "Subscription plan tier ratio",
            "series": series,
        }

    async def _widget_payment_status(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Payment status widget — pie chart of invoice statuses."""
        series = await self.repository.aggregate_payment_status()

        return {
            "widget": "payment_status",
            "chart_type": "pie",
            "title": "Payment Status",
            "subtitle": "Invoice fulfillment ratio",
            "series": series,
        }

    # ── Chart Type Reshape Engine ────────────────────────────────────────
    #
    # When the frontend overrides chart_type via ?chart_type= query param,
    # this method transforms the series data to match the target shape.
    #
    # Shape Groups:
    #   A (category): pie, donut, funnel  → [{name, value}]
    #   B (sequential): line, bar, area   → [{label, value}]
    #   C (xy): scatter                   → [{x, y, name?}]
    #   D (multi-axis): radar             → [{name, value, max?}]
    #   E (single): gauge                 → {value, max?, label?}
    #   F (grid): heatmap                 → [{x, y, value}]
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _reshape_widget(widget: Dict[str, Any], target_type: str) -> Dict[str, Any]:
        """Reshape series data when frontend overrides chart_type.

        Handles all cross-group transformations between 6 shape groups.
        Lossy transformations (dimension reduction) are logged but allowed.
        """
        import math

        GROUP_A = {"pie", "donut", "funnel"}
        GROUP_B = {"line", "bar", "area"}
        GROUP_C = {"scatter"}
        GROUP_D = {"radar"}
        GROUP_E = {"gauge"}
        GROUP_F = {"heatmap"}

        source_type = widget.get("chart_type")
        series = widget.get("series", [])

        # Resolve shape groups for source and target
        src_group = (
            "A" if source_type in GROUP_A else
            "B" if source_type in GROUP_B else
            "C" if source_type in GROUP_C else
            "D" if source_type in GROUP_D else
            "E" if source_type in GROUP_E else
            "F" if source_type in GROUP_F else None
        )
        tgt_group = (
            "A" if target_type in GROUP_A else
            "B" if target_type in GROUP_B else
            "C" if target_type in GROUP_C else
            "D" if target_type in GROUP_D else
            "E" if target_type in GROUP_E else
            "F" if target_type in GROUP_F else None
        )

        # Same group → no reshape needed, just swap chart_type
        if src_group == tgt_group:
            return {**widget, "chart_type": target_type, "series": series}

        # Compute max_val for transformations that need scale reference
        max_val = 0
        if isinstance(series, list) and series:
            max_val = max((s.get("value", 0) for s in series), default=0)

        # ── Cross-group transformations ───────────────────────────────
        if src_group == "A" and tgt_group == "B":
            series = [{"label": s.get("name", ""), "value": s.get("value", 0)} for s in series]

        elif src_group == "B" and tgt_group == "A":
            series = [{"name": s.get("label", ""), "value": s.get("value", 0)} for s in series]

        elif src_group == "A" and tgt_group == "C":
            series = [
                {"x": i, "y": s.get("value", 0), "name": s.get("name", "")}
                for i, s in enumerate(series)
            ]

        elif src_group == "B" and tgt_group == "C":
            series = [
                {"x": i, "y": s.get("value", 0), "name": s.get("label", "")}
                for i, s in enumerate(series)
            ]

        elif src_group == "A" and tgt_group == "D":
            ceil_max = math.ceil(max_val * 1.2) if max_val else 100
            series = [
                {"name": s.get("name", ""), "value": s.get("value", 0), "max": ceil_max}
                for s in series
            ]

        elif src_group == "B" and tgt_group == "D":
            ceil_max = math.ceil(max_val * 1.2) if max_val else 100
            series = [
                {"name": s.get("label", ""), "value": s.get("value", 0), "max": ceil_max}
                for s in series
            ]

        elif src_group == "A" and tgt_group == "E":
            # Lossy: reduces multiple categories to single total
            total = sum(s.get("value", 0) for s in series)
            series = {"value": total, "max": total, "label": "Total"}

        elif src_group == "B" and tgt_group == "E":
            # Lossy: takes last data point as the gauge value
            last = series[-1] if series else {"label": "", "value": 0}
            series = {"value": last.get("value", 0), "max": max_val, "label": last.get("label", "")}

        elif src_group == "C" and tgt_group == "A":
            # Lossy: loses x axis
            series = [
                {"name": s.get("name", f"Point {i}"), "value": s.get("y", 0)}
                for i, s in enumerate(series)
            ]

        elif src_group == "C" and tgt_group == "B":
            # Lossy: loses precise x coordinates
            series = [
                {"label": s.get("name", str(s.get("x", i))), "value": s.get("y", 0)}
                for i, s in enumerate(series)
            ]

        elif src_group == "D" and tgt_group == "A":
            # Lossy: loses max scale
            series = [{"name": s.get("name", ""), "value": s.get("value", 0)} for s in series]

        elif src_group == "D" and tgt_group == "B":
            # Lossy: loses max scale
            series = [{"label": s.get("name", ""), "value": s.get("value", 0)} for s in series]

        elif src_group == "E" and tgt_group == "A":
            if isinstance(series, dict):
                val = series.get("value", 0)
                mx = series.get("max", val)
                lbl = series.get("label", "Value")
                series = [
                    {"name": lbl, "value": val},
                    {"name": "Remaining", "value": max(0, mx - val)},
                ]
            else:
                series = []

        elif src_group == "E" and tgt_group == "B":
            if isinstance(series, dict):
                series = [{"label": series.get("label", "Value"), "value": series.get("value", 0)}]
            else:
                series = []

        elif src_group == "F" and tgt_group == "B":
            # Lossy: collapses y axis via summation by x
            buckets: Dict[str, float] = {}
            for s in series:
                key = str(s.get("x", ""))
                buckets[key] = buckets.get(key, 0) + s.get("value", 0)
            series = [{"label": k, "value": v} for k, v in buckets.items()]

        elif src_group == "F" and tgt_group == "A":
            # Lossy: collapses y axis via summation by x
            buckets_a: Dict[str, float] = {}
            for s in series:
                key = str(s.get("x", ""))
                buckets_a[key] = buckets_a.get(key, 0) + s.get("value", 0)
            series = [{"name": k, "value": v} for k, v in buckets_a.items()]

        else:
            # Unsupported cross-group: return as-is with target type
            logger.warning(
                "Unsupported reshape %s(%s) → %s — returning raw series",
                source_type, src_group, target_type,
            )

        return {**widget, "chart_type": target_type, "series": series}

