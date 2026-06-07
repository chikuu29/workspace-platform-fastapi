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
                    "existing_record_id": existing["_meta"]["record_id"],
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
                "record_id": document["_meta"]["record_id"],
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
                details={"existing_record_id": existing["_meta"]["record_id"]},
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
                "record_id": document["_meta"]["record_id"],
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
        """
        Retrieve dashboard KPIs.
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

        recent_docs = await self.repository.find(
            MEMBER_QUERY,
            sort=[("_meta.created.at", -1)],
            limit=5,
        )
        recent_members = []
        for d in recent_docs:
            enriched = await self._enrich_member(d)
            recent_members.append({
                "record_id": enriched["_meta"]["record_id"],
                "name": (
                    f"{enriched['data'].get('firstName', '')} "
                    f"{enriched['data'].get('lastName', '')}"
                ).strip() or "Unknown",
                "plan": enriched["data"].get("plan", "N/A"),
                "created_at": enriched["_meta"]["created"]["at"],
                "status": enriched["data"].get("status", "active"),
            })

        revenue_pipeline = [
            {"$match": {**self._ctx.active_filter, **SUBSCRIPTION_QUERY, "data.status": "active"}},
            {"$group": {"_id": None, "total": {"$sum": "$data.price"}}},
        ]
        revenue_result = await self.repository.collection.aggregate(revenue_pipeline).to_list(length=1)
        revenue_mrr = revenue_result[0]["total"] if revenue_result else 0

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        checkins_today = await self.repository.count_attendance_since(today_start)

        total_trainers = await self.repository.count_trainers()
        active_trainers = await self.repository.count({**TRAINER_QUERY, "data.status": "active"})
        trainer_utilization = (
            round(active_trainers / total_trainers * 100) if total_trainers > 0 else 0
        )

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

    async def get_subscription_analytics(self) -> Dict[str, Any]:
        """
        Retrieve subscription analytics.
        """
        total_plans = await self.repository.count_plans()
        active_plans = await self.repository.count_plans(active_only=True)
        total_subscribers = await self.repository.count({
            **SUBSCRIPTION_QUERY,
            "data.status": "active",
        })

        plan_docs = await self.repository.find_plans(active_only=True, limit=50)

        plans_with_members = []
        total_mrr = 0.0

        for plan in plan_docs:
            plan_code = plan["data"].get("code", "")
            member_count = await self.repository.count({
                **SUBSCRIPTION_QUERY,
                "data.plan_code": plan_code,
                "data.status": "active",
            })

            price = plan["data"].get("price", 0)
            billing_cycle = plan["data"].get("billing_cycle", "monthly")

            if billing_cycle == "quarterly":
                monthly_price = price / 3
            elif billing_cycle == "yearly":
                monthly_price = price / 12
            else:
                monthly_price = price

            plan_revenue = monthly_price * member_count
            total_mrr += plan_revenue

            plans_with_members.append({
                "plan_code": plan_code,
                "plan_name": plan["data"].get("name", ""),
                "price": price,
                "billing_cycle": billing_cycle,
                "member_count": member_count,
                "revenue": round(plan_revenue, 2),
                "accent_color": plan["data"].get("accent_color", "blue"),
            })

        return {
            "total_plans": total_plans,
            "active_plans": active_plans,
            "total_subscribers": total_subscribers,
            "total_mrr": round(total_mrr, 2),
            "plans_with_members": plans_with_members,
        }

    async def get_attendance_analytics(self) -> Dict[str, Any]:
        """
        Retrieve check-in/attendance heatmap and daily visits.
        """
        now = datetime.now(timezone.utc)
        dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        daily_visits = []
        for d in reversed(dates):
            count = await self.repository.count({**ATTENDANCE_QUERY, "data.date": d})
            daily_visits.append({"date": d, "count": count})

        hourly_dist: dict[int, int] = {h: 0 for h in range(24)}
        checkins = await self.repository.find_attendance(limit=1000)
        for checkin in checkins:
            hour = checkin["data"].get("hour")
            if hour is not None:
                hourly_dist[hour] += 1

        heatmap = [{"hour": h, "count": c} for h, c in hourly_dist.items()]

        seven_days_ago = (now - timedelta(days=7)).isoformat()
        active_member_ids = await self.repository.find_attendance_member_ids_since(seven_days_ago)

        total_members = await self.repository.count_members()

        return {
            "daily_visits": daily_visits,
            "hourly_heatmap": heatmap,
            "active_last_7_days": len(active_member_ids),
            "total_members": total_members,
            "slipping_members": max(0, total_members - len(active_member_ids)),
        }
