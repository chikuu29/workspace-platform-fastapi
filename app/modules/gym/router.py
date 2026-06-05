"""
Gym Module Router — thin aggregator.

All business logic lives in the sub-routers under gym/routers/.
This file simply wires them together and applies the shared
authentication dependency once at the top level so every
included sub-router inherits it automatically.

Response contract (via app.common.responses):
    Success → { "success": True,  "message": "...", "data": {...} }
    Error   → { "success": False, "message": "...", "error_code": "..." }

Sub-router ownership:
    analytics.py     — GET /analytics/*
    members.py       — /addMember, /members, /members/{id}
    plans.py         — /plans, /plans/{id}
    subscriptions.py — /subscriptions/activate  (legacy direct-pay flow)
    membership.py    — /membership/enroll, /membership/{id}/collect-payment,
                       /membership/{id}/send-payment-link
    invoices.py      — /membership/create-invoice, /invoices/{n}/*, webhooks
    trainers.py      — /addTrainer, /trainers, /trainers/{id}
    attendance.py    — /checkin
"""

from fastapi import APIRouter, Depends

from app.core.security.authentications import get_authenticated_identity

from app.modules.gym.routers import (
    analytics,
    members,
    plans,
    subscriptions,
    membership,
    invoices,
    trainers,
    attendance,
)

# Auth dependency applied once here — every sub-router inherits it.
# Sub-routers use plain APIRouter() to avoid double-application.
router = APIRouter(
    dependencies=[Depends(get_authenticated_identity)]
)

router.include_router(analytics.router)
router.include_router(members.router)
router.include_router(plans.router)
router.include_router(subscriptions.router)
router.include_router(membership.router)
router.include_router(invoices.router)
router.include_router(trainers.router)
router.include_router(attendance.router)
