import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import jwt
from app.core.config import settings
# from app.modules.auth.repository import AuthRepository
from app.core.logger import create_logger

class AuthService:
    """
    Encapsulates core authentication and session coordination business logic.
    """
    def __init__(self):
        # self.repository = repository
        self.logger = create_logger("auth_service")

    def get_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def generate_local_tokens(self, payload: Dict[str, Any]) -> Dict[str, str]:
        issued_at = int(time.time())
        access_token = jwt.encode(
            {
                **payload,
                "exp": issued_at + settings.LOCAL_ACCESS_TOKEN_EXPIRE_SECONDS,
                "iat": issued_at,
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        refresh_token = jwt.encode(
            {
                **payload,
                "exp": issued_at + settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
                "iat": issued_at,
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    def parse_datetime(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            normalized = value.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return None
        return None

    def parse_user_agent(self, user_agent: str) -> Dict[str, Any]:
        lowered = user_agent.lower()
        browser, version, os_name = "Unknown", "Unknown", "Unknown"

        if "edg" in lowered: browser = "Edge"
        elif "chrome" in lowered: browser = "Chrome"
        elif "firefox" in lowered: browser = "Firefox"
        elif "safari" in lowered: browser = "Safari"
        elif "trident" in lowered or "msie" in lowered: browser = "Internet Explorer"

        markers = {"Edge": "Edg/", "Chrome": "Chrome/", "Firefox": "Firefox/", "Safari": "Version/", "Internet Explorer": "MSIE "}
        marker = markers.get(browser)
        if marker and marker in user_agent:
            version = user_agent.split(marker, maxsplit=1)[1].split(" ", maxsplit=1)[0].split(")", maxsplit=1)[0]

        for candidate in ("windows", "mac", "linux", "android", "iphone", "ipad"):
            if candidate in lowered:
                os_name = candidate
                break

        return {
            "browser": browser,
            "os": os_name,
            "browserDetails": {"browser": browser, "version": version},
        }

   