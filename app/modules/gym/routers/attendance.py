"""
gym/routers/attendance.py — Member check-in recording.

Endpoints:
    POST /checkin — Record a member attendance / check-in event
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.context import OrgContext, get_org_context
from app.common.org_repository import OrgRepository
from app.common.responses import created, not_found, bad_request
from app.db.database import get_database
from app.modules.gym.routers.constants import (
    ENTITY_ATTENDANCE,
    MEMBER_QUERY,
    SUBSCRIPTION_QUERY,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
#  ATTENDANCE & CHECK-IN
# ══════════════════════════════════════════════════════════════════════

@router.post("/checkin")
async def member_checkin(
    data: dict,
    ctx: OrgContext = Depends(get_org_context),
    db=Depends(get_database),
):
    """
    Record a member check-in event.

    Payload:
        { "member_id": "M-11" }

    Creates an attendance document enriched with:
    - Member name (looked up from the records collection)
    - Current timestamp / date / hour for heatmap analytics
    - Active subscription reference (if any) for churn analysis
    """
    repo = OrgRepository(db, "records", ctx)
    member_id = data.get("member_id")

    if not member_id:
        bad_request(message="member_id is required.")

    # 1. Verify member exists
    member_doc = await repo.find_one({**MEMBER_QUERY, "data.member_id": member_id})
    if not member_doc:
        not_found(message=f"Member {member_id} not found.")

    # 2. Look up active subscription (optional — used for analytics only)
    sub = await repo.find_one({
        **SUBSCRIPTION_QUERY,
        "data.member_id": member_id,
        "data.status": "active",
    })

    # 3. Create attendance record
    now = datetime.now(timezone.utc)
    checkin_data = {
        "member_id": member_id,
        "member_name": (
            f"{member_doc['data'].get('firstName', '')} "
            f"{member_doc['data'].get('lastName', '')}"
        ).strip(),
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        # Hour stored separately for efficient hourly heatmap aggregation
        "hour": now.hour,
        "subscription_id": sub["data"]["subscription_id"] if sub else None,
        "has_active_plan": bool(sub),
    }

    doc = await repo.insert_one(
        data=checkin_data,
        entity_type=ENTITY_ATTENDANCE,
        prefix=ctx.app_code.upper(),
    )

    return created(message="Check-in successful!", data=doc)
