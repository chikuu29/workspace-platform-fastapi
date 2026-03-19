import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.development", override=False)


def _split_csv_env(value: Optional[str], default: List[str]) -> List[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_json_env(value: Optional[str], default: Dict[str, str]) -> Dict[str, str]:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default

    if not isinstance(parsed, dict):
        return default

    return {str(key): str(val) for key, val in parsed.items()}


class Settings(BaseModel):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Workspace Platform API")
    VERSION: str = os.getenv("VERSION", "1.0.0")
    API_V1_STR: str = os.getenv("API_V1_STR", "/api/v1")
    NODE_ENV: str = os.getenv("NODE_ENV", "development")

    BACKEND_CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: _split_csv_env(
            os.getenv("BACKEND_CORS_ORIGINS"),
            ["http://localhost:5173"],
        )
    )

    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "workspace_db")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))
    LOCAL_ACCESS_TOKEN_EXPIRE_SECONDS: int = int(os.getenv("LOCAL_ACCESS_TOKEN_EXPIRE_SECONDS", "3600"))
    LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS: int = int(os.getenv("LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS", "86400"))

    OAUTH_OPENID_CONFIG_URL: str = os.getenv(
        "OAUTH_OPENID_CONFIG_URL",
        "http://localhost:8000/.well-known/openid-configuration",
    )
    OAUTH_CLIENT_ID: str = os.getenv("OAUTH_CLIENT_ID", "")
    OAUTH_CLIENT_SECRET: str = os.getenv("OAUTH_CLIENT_SECRET", "")
    OAUTH_TOKEN_URI: Optional[str] = os.getenv("OAUTH_TOKEN_URI")

    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", os.getenv("OAUTH_CLIENT_ID", ""))
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", os.getenv("OAUTH_CLIENT_SECRET", ""))
    GOOGLE_OAUTH_CALLBACK_URL: str = os.getenv(
        "GOOGLE_OAUTH_CALLBACK_URL",
        "http://localhost:7000/api/v1/oauth/google/callback",
    )
    GOOGLE_AUTH_URL: str = os.getenv("GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")
    GOOGLE_TOKEN_URL: str = os.getenv("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")
    GOOGLE_USERINFO_URL: str = os.getenv(
        "GOOGLE_USERINFO_URL",
        "https://openidconnect.googleapis.com/v1/userinfo",
    )

    X_CLIENT_IDS: List[str] = Field(
        default_factory=lambda: _split_csv_env(os.getenv("X_CLIENT_IDS"), ["LOCAL_BASELINE"])
    )
    APP_COLLECTION_MAP: Dict[str, str] = Field(
        default_factory=lambda: _parse_json_env(os.getenv("APP_COLLECTION_MAP"), {"myGym": "myGym"})
    )

    STORAGE_ROOT: Path = BASE_DIR / "storage"
    FILE_UPLOAD_URL: str = os.getenv("FILE_UPLOAD_URL", "http://localhost:7000/public/storage/")

    @property
    def is_production(self) -> bool:
        return self.NODE_ENV.lower() == "production"

    @property
    def session_cookie_name(self) -> str:
        prefix = "__Secure-" if self.is_production else ""
        return f"{prefix}session-token"

    @property
    def allowed_client_ids(self) -> set[str]:
        return {client_id for client_id in self.X_CLIENT_IDS if client_id}


settings = Settings()
