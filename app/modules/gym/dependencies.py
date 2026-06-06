"""
Gym Module Dependencies — Dependency injection helpers for routers.
"""

from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_db
from app.core.context import OrgContext, get_org_context
from app.modules.gym.repository import GymRepository
from app.modules.gym.service import GymService


def get_gym_repository(
    db: AsyncIOMotorDatabase = Depends(get_db),
    ctx: OrgContext = Depends(get_org_context),
) -> GymRepository:
    """FastAPI dependency to instantiate the GymRepository."""
    return GymRepository(db, ctx)


def get_gym_service(
    repository: GymRepository = Depends(get_gym_repository),
    db: AsyncIOMotorDatabase = Depends(get_db),
    ctx: OrgContext = Depends(get_org_context),
) -> GymService:
    """FastAPI dependency to instantiate the GymService."""
    return GymService(repository, db, ctx)
