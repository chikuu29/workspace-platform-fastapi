from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.database import get_database
from app.modules.users.repository import UserRepository
from app.modules.users.service import UserService

def get_user_repository(db: AsyncIOMotorDatabase = Depends(get_database)) -> UserRepository:
    return UserRepository(db)

def get_user_service(repo: UserRepository = Depends(get_user_repository)) -> UserService:
    return UserService(repo)
