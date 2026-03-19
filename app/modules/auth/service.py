import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import jwt
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.core.errors import ApiError
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.core.logger import create_logger

class AuthService:
    """
    Encapsulates core authentication and session coordination business logic.
    """
    def __init__(self, repository: AuthRepository):
        self.repository = repository
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

    async def register(self, payload: RegisterRequest) -> Dict[str, Any]:
        self.logger.info(f"Attempting to register user with email/phone: {payload.email or payload.phone}")
        existing_user = await self.repository.find_user_by_login(payload.email) or await self.repository.find_user_by_login(payload.phone)
        if existing_user:
            self.logger.warning(f"Registration failed: User {payload.userName} already exists")
            raise ApiError(409, "User already exists", payload={"error": f"User: {payload.userName} already exists"})

        user_doc = payload.model_dump()
        user_doc.update({
            "password": get_password_hash(user_doc["password"]),
            "role": "user",
            "registerMode": "MANUAL",
            "image": None,
            "devices": [],
            "numOfLoginFailAttempt": 0,
            "blockTillLogInTimeStamp": self.get_now_iso(),
            "createdAt": self.get_now_iso()
        })
        await self.repository.register_user(user_doc)
        
        response_data = payload.model_dump()
        response_data.pop("password", None)
        self.logger.info(f"User {payload.userName} registered successfully")
        return response_data

    async def login(self, payload: LoginRequest, ip: str, user_agent: str, client_name: str) -> Dict[str, Any]:
        self.logger.info(f"Login attempt for user: {payload.loginId} from IP: {ip}")
    async def login(self, payload: LoginRequest, ip: str, user_agent: str, client_name: str) -> Dict[str, Any]:
        self.logger.info(f"Login attempt for user: {payload.loginId} from IP: {ip}")
        user = await self.repository.find_user_by_login(payload.loginId)
        if not user:
            self.logger.warning(f"Login failed: User {payload.loginId} not found")
            raise ApiError(404, "User Not Found", payload={"error": "User does not exist"})

        blocked_until = self.parse_datetime(user.get("blockTillLogInTimeStamp"))
        now_utc = datetime.now(timezone.utc)
        if blocked_until:
            if blocked_until.tzinfo is None:
                blocked_until = blocked_until.replace(tzinfo=timezone.utc)
            if blocked_until > now_utc:
                self.logger.warning(f"Login blocked for user {payload.loginId} until {blocked_until}")
                raise ApiError(401, "Your account is blocked due to too many failed login attempts.")

        stored_password = user.get("password")
        if not stored_password or not verify_password(payload.password, stored_password):
            self.logger.warning(f"Login failed: Incorrect password for user {payload.loginId}")
            raise ApiError(401, "Incorrect password", payload={"error": "Incorrect password"})

        device_info = {
            **self.parse_user_agent(user_agent),
            "dateTimeAt": self.get_now_iso(),
            "ip": ip,
        }
        devices = user.get("devices", [])
        known_device = next((d for d in devices if d.get("ip") == device_info["ip"] and d.get("browser") == device_info["browser"]), None)
        
        if not known_device:
            devices.append(device_info)
            await self.repository.add_device_to_user(str(user["_id"]), devices)

        token_payload = {
            "authProvider": "MANUAL_LOGIN_MODE",
            "userName": user.get("userName"),
            "firstName": user.get("firstName"),
            "lastName": user.get("lastName"),
            "image": user.get("image"),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "role": user.get("role", "user"),
            "clientName": client_name,
        }
        tokens = self.generate_local_tokens(token_payload)

        self.logger.info(f"Login successful for user {payload.loginId}")
        return {
            "user": user,
            "tokens": tokens
        }
