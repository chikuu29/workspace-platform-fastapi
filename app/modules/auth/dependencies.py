from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.database import get_database
# from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService

# def get_auth_repository(db: AsyncIOMotorDatabase = Depends(get_database)) -> AuthRepository:
#     return AuthRepository(db)

def get_auth_service() -> AuthService:
    return AuthService()
