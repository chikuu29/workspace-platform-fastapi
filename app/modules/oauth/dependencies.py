from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.db.database import get_database
from app.modules.oauth.repository import OAuthRepository
from app.modules.oauth.service import OAuthService

def get_oauth_repository(db: AsyncIOMotorDatabase = Depends(get_database)) -> OAuthRepository:
    return OAuthRepository(db)

def get_oauth_service(repo: OAuthRepository = Depends(get_oauth_repository)) -> OAuthService:
    return OAuthService(repo)
