from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_db
from app.modules.system.repository import AppRepository
from app.modules.system.service import AppService

def get_app_repository(db: AsyncIOMotorDatabase = Depends(get_db)) -> AppRepository:
    return AppRepository(db)

def get_app_service(repo: AppRepository = Depends(get_app_repository)) -> AppService:
    return AppService(repo)
