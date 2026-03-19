from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.database import get_database
from app.modules.app.repository import AppRepository
from app.modules.app.service import AppService

def get_app_repository(db: AsyncIOMotorDatabase = Depends(get_database)) -> AppRepository:
    return AppRepository(db)

def get_app_service(repo: AppRepository = Depends(get_app_repository)) -> AppService:
    return AppService(repo)
