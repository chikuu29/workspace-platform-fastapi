import json
from pathlib import Path
from typing import Annotated, Dict, List

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.development", override=True)


class Settings(BaseSettings):
    """
    Application settings managed by environment variables.
    """

    model_config = SettingsConfigDict(extra="ignore")

    PROJECT_NAME: str = "Workspace Platform API"
    VERSION: str = "1.0.0"
    # WHY "/v1" not "/api/v1":
    # root_path="/api" in main.py already contributes the /api segment to
    # Swagger's generated URLs.  If this were "/api/v1", every route would
    # appear as /api/api/v1/... in Swagger and all proxy rewrites would break.
    # Actual request path chain:
    #   PROD: nginx strips /api  → pod receives /v1/route  ✅
    #   DEV:  vite strips /backend → pod receives /v1/route ✅
    API_V1_STR: str = "/v1"
    PORT: int = 8001
    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost", "http://localhost:3000"],
        validation_alias=AliasChoices("BACKEND_CORS_ORIGINS", "CORS_ORIGINS"),
    )
    # Keep static files anchored to the backend app directory. A relative
    # "storage" path depends on the shell cwd used to launch uvicorn, which
    # can make uploaded files exist on disk but 404 from /public/storage.
    STORAGE_ROOT: Path = BASE_DIR / "storage"
    FILE_UPLOAD_URL: str = "/public/storage"
    APP_NAME: str = "Workspace API"
    ENV: str = Field(default="development", validation_alias=AliasChoices("ENV", "NODE_ENV"))
    LOG_LEVEL: str = "INFO"

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = Field(
        default="workspace_saas",
        validation_alias=AliasChoices("DATABASE_NAME", "MONGO_DB_NAME"),
    )

    # OAuth2 client
    OAUTH_CLIENT_ID: str = ""
    OAUTH_CLIENT_SECRET: str = ""
    OAUTH_TOKEN_URI: str = ""
    OAUTH_OPENID_CONFIG_URL: str = ""

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_CALLBACK_URL: str = ""
    GOOGLE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL: str = "https://openidconnect.googleapis.com/v1/userinfo"

    # JWT/local auth
    SECRET_KEY: str = "supersecretkey_change_me_in_prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    LOCAL_ACCESS_TOKEN_EXPIRE_SECONDS: int = 1800
    LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS: int = 604800
    session_cookie_name: str = Field(
        default="session_token",
        validation_alias=AliasChoices("SESSION_COOKIE_NAME", "SESSION_COOKIE"),
    )

    # App-specific settings
    allowed_client_ids: Annotated[List[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="ALLOWED_CLIENT_IDS",
    )
    APP_COLLECTION_MAP: Annotated[Dict[str, str], NoDecode] = Field(default_factory=dict)

    @field_validator("BACKEND_CORS_ORIGINS", "allowed_client_ids", mode="before")
    @classmethod
    def _parse_list_values(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("APP_COLLECTION_MAP", mode="before")
    @classmethod
    def _parse_dict_values(cls, value: object) -> object:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            return json.loads(value)
        return value

    @model_validator(mode="after")
    def _apply_fallbacks(self) -> "Settings":
        if not self.allowed_client_ids and self.OAUTH_CLIENT_ID:
            self.allowed_client_ids = [self.OAUTH_CLIENT_ID]
        return self

    @property
    def MONGO_DB_NAME(self) -> str:
        return self.DATABASE_NAME

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"


settings = Settings()
