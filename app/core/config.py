from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from pathlib import Path

class Settings(BaseSettings):
    """
    Application settings managed by environment variables.
    """
    PROJECT_NAME: str = "Workspace Platform API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost", "http://localhost:3000"]
    STORAGE_ROOT: Path = Path("storage")
    APP_NAME: str = "Workspace API"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # MongoDB Connect
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "workspace_saas"

    # JWT Authentication
    SECRET_KEY: str = "supersecretkey_change_me_in_prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    model_config = SettingsConfigDict(
