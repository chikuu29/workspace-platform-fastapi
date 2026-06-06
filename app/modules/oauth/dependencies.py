from fastapi import Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.core.database import get_db
from app.modules.oauth.repository import OAuthRepository
from app.modules.oauth.service import OAuthService

def get_oauth_repository(db: AsyncIOMotorDatabase = Depends(get_db)) -> OAuthRepository:
    return OAuthRepository(db)

def get_oauth_service(repo: OAuthRepository = Depends(get_oauth_repository)) -> OAuthService:
    return OAuthService(repo)
