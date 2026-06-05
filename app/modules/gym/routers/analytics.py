"""
gym/routers/analytics.py — Dashboard KPI, subscription stats, and attendance analytics.

Endpoints:
    GET /analytics/kpis            — Dashboard member + revenue + check-in KPIs
    GET /analytics/subscriptions   — Per-plan subscriber counts + MRR breakdown
    GET /analytics/attendance      — Daily visits, hourly heatmap, active members
"""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import ok
from app.db.database import get_database
from app.modules.gym.routers.constants import (
    MEMBER_QUERY,
    PLAN_QUERY,
    SUBSCRIPTION_QUERY,
    ATTENDANCE_QUERY,
    TRAINER_QUERY,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD KPIs
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/kpis")
async def get_gym_kpis(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Aggregate gym dashboard KPI data in a single backend call.

    Returns member counts by status, the 5 most recently enrolled
    members, real-time revenue MRR, today's check-in count, and
    trainer utilisation percentage.
    """
    repo = OrgRepository(db, "records", ctx)

    # ── Member status counts ─────────────────────────────────────────
    total = await repo.count(MEMBER_QUERY)
    active = await repo.count({**MEMBER_QUERY, "data.status": "active"})
    attention = await repo.count({**MEMBER_QUERY, "data.status": "attention"})
    frozen = await repo.count({**MEMBER_QUERY, "data.status": "frozen"})

    # ── Monthly additions ─────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    month_start = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    added_this_month = await repo.count({
        **MEMBER_QUERY,
        "_meta.created.at": {"$gte": month_start},
    })

    # ── Recent members (5 most recently enrolled) ────────────────────
    recent_docs = await repo.find(
        MEMBER_QUERY,
        sort=[("_meta.created.at", -1)],
        limit=5,
    )
    recent_members = [
        {
            "record_id": d["_meta"]["record_id"],
            "name": (
                f"{d['data'].get('firstName', '')} "
                f"{d['data'].get('lastName', '')}"
            ).strip() or "Unknown",
            "plan": d["data"].get("plan", "N/A"),
            "created_at": d["_meta"]["created"]["at"],
        }
        for d in recent_docs
    ]

    # ── Revenue MRR — sum prices from all active subscriptions ───────
    revenue_pipeline = [
        {"$match": {**ctx.active_filter, **SUBSCRIPTION_QUERY, "data.status": "active"}},
        {"$group": {"_id": None, "total": {"$sum": "$data.price"}}},
    ]
    revenue_result = await repo.collection.aggregate(revenue_pipeline).to_list(length=1)
    revenue_mrr = revenue_result[0]["total"] if revenue_result else 0

    # ── Check-ins today (UTC day boundary) ───────────────────────────
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    checkins_today = await repo.count({
        **ATTENDANCE_QUERY,
        "_meta.created.at": {"$gte": today_start},
    })

    # ── Trainer utilisation — active / total ─────────────────────────
    total_trainers = await repo.count(TRAINER_QUERY)
    active_trainers = await repo.count({**TRAINER_QUERY, "data.status": "active"})
    trainer_utilization = (
        round(active_trainers / total_trainers * 100) if total_trainers > 0 else 0
    )

    return ok(
        message="Dashboard statistics retrieved.",
        data={
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
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  SUBSCRIPTION ANALYTICS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/subscriptions")
async def get_subscription_analytics(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Aggregate subscription dashboard KPIs.

    Returns plan counts, subscriber counts, and revenue breakdown
    per plan (normalised to monthly for MRR calculation).
    """
    repo = OrgRepository(db, "records", ctx)

    # ── Plan-level counts ─────────────────────────────────────────────
    total_plans = await repo.count(PLAN_QUERY)
    active_plans = await repo.count({**PLAN_QUERY, "data.is_active": True})

    # ── Active subscriber count ───────────────────────────────────────
    total_subscribers = await repo.count({
        **SUBSCRIPTION_QUERY,
        "data.status": "active",
    })

    # ── Per-plan breakdown ────────────────────────────────────────────
    plan_docs = await repo.find(
        {**PLAN_QUERY, "data.is_active": True},
        sort=[("data.price", -1)],
        limit=50,
    )

    plans_with_members = []
    total_mrr = 0.0

    for plan in plan_docs:
        plan_code = plan["data"].get("code", "")
        member_count = await repo.count({
            **SUBSCRIPTION_QUERY,
            "data.plan_code": plan_code,
            "data.status": "active",
        })

        price = plan["data"].get("price", 0)
        billing_cycle = plan["data"].get("billing_cycle", "monthly")

        # Normalise to monthly revenue for consistent MRR reporting
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

    return ok(
        message="Subscription stats retrieved.",
        data={
            "total_plans": total_plans,
            "active_plans": active_plans,
            "total_subscribers": total_subscribers,
            "total_mrr": round(total_mrr, 2),
            "plans_with_members": plans_with_members,
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  ATTENDANCE ANALYTICS
# ══════════════════════════════════════════════════════════════════════

@router.get("/analytics/attendance")
async def get_attendance_analytics(
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Get attendance analytics: daily visits, hourly heatmap, and
    active vs slipping member counts.
    """
    repo = OrgRepository(db, "records", ctx)
    now = datetime.now(timezone.utc)

    # ── Daily visits — last 7 days ────────────────────────────────────
    dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    daily_visits = []
    for d in reversed(dates):
        count = await repo.count({**ATTENDANCE_QUERY, "data.date": d})
        daily_visits.append({"date": d, "count": count})

    # ── Hourly heatmap — distribute last 1000 check-ins by hour ──────
    # Using a Python-side aggregation to avoid complex pipelines.
    hourly_dist: dict[int, int] = {h: 0 for h in range(24)}
    checkins = await repo.find(ATTENDANCE_QUERY, limit=1000)
    for checkin in checkins:
        hour = checkin["data"].get("hour")
        if hour is not None:
            hourly_dist[hour] += 1

    heatmap = [{"hour": h, "count": c} for h, c in hourly_dist.items()]

    # ── Active members — checked in within the last 7 days ───────────
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    active_member_ids = await db["records"].distinct(
        "data.member_id",
        {
            **ATTENDANCE_QUERY,
            "_org.org_id": ctx.org_id,
            "data.timestamp": {"$gte": seven_days_ago},
        },
    )

    total_members = await repo.count(MEMBER_QUERY)

    return ok(
        data={
            "daily_visits": daily_visits,
            "hourly_heatmap": heatmap,
            "active_last_7_days": len(active_member_ids),
            "total_members": total_members,
            "slipping_members": max(0, total_members - len(active_member_ids)),
        },
    )
