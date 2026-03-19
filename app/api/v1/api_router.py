from fastapi import APIRouter

from app.modules.app.router import router as app_router
from app.modules.auth.router import router as auth_router
from app.modules.gym.router import router as gym_router
from app.modules.oauth.router import router as oauth_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(oauth_router, prefix="/oauth", tags=["oauth"])
api_router.include_router(app_router, prefix="/app", tags=["app"])
api_router.include_router(gym_router, prefix="/gym", tags=["gym"])
