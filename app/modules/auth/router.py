import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, Request, Response
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies import extract_bearer_token, require_request_context
from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client
from app.core.responses import success_response
from app.core.security import get_password_hash, verify_password
from app.db.database import get_database
from app.modules.auth.schemas import LoginRequest, RegisterRequest

router = APIRouter()


def _get_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_local_tokens(payload: Dict[str, Any]) -> Dict[str, str]:
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


def _set_cookie(
    response: Response,
    key: str,
    value: str,
    *,
    max_age: Optional[int] = None,
    same_site: str = "lax",
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=settings.is_production,
        samesite=same_site,
        path="/",
        max_age=max_age,
    )


def _clear_cookie(response: Response, key: str, *, same_site: str = "lax") -> None:
    response.delete_cookie(
        key=key,
        httponly=True,
        secure=settings.is_production,
        samesite=same_site,
        path="/",
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    return None


def _parse_user_agent(user_agent: str) -> Dict[str, Any]:
    lowered = user_agent.lower()
    browser = "Unknown"
    version = "Unknown"
    os_name = "Unknown"

    if "edg" in user_agent:
        browser = "Edge"
    elif "chrome" in user_agent:
        browser = "Chrome"
    elif "firefox" in user_agent:
        browser = "Firefox"
    elif "safari" in user_agent:
        browser = "Safari"
    elif "trident" in lowered or "msie" in lowered:
        browser = "Internet Explorer"

    markers = {
        "Edge": "Edg/",
        "Chrome": "Chrome/",
        "Firefox": "Firefox/",
        "Safari": "Version/",
        "Internet Explorer": "MSIE ",
    }
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
        "browserDetails": {
            "browser": browser,
            "version": version,
        },
    }


@router.post("/register")
async def register_user(
    payload: RegisterRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context=Depends(require_request_context),
):
    existing_user = await db["user"].find_one(
        {
            "$or": [
                {"email": payload.email},
                {"phone": payload.phone},
            ]
        }
    )
    if existing_user:
        raise ApiError(
            409,
            "User already exists",
            payload={"error": f"User: {payload.userName} already exists"},
        )

    user_doc = payload.model_dump()
    user_doc["password"] = get_password_hash(user_doc["password"])
    user_doc["role"] = "user"
    user_doc["registerMode"] = "MANUAL"
    user_doc["image"] = None
    user_doc["devices"] = []
    user_doc["numOfLoginFailAttempt"] = 0
    user_doc["blockTillLogInTimeStamp"] = _get_now_iso()
    user_doc["createdAt"] = _get_now_iso()

    await db["user"].insert_one(user_doc)

    response_data = payload.model_dump()
    response_data.pop("password", None)
    return success_response(
        payload={
            "projectName": request_context.client_name,
            "data": response_data,
        },
        message=f"User: {payload.userName} registered successfully",
    )


@router.post("/login")
async def login_user(
    payload: LoginRequest,
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_database),
    request_context=Depends(require_request_context),
):
    user = await db["user"].find_one(
        {
            "$or": [
                {"email": payload.loginId},
                {"phone": payload.loginId},
            ]
        }
    )
    if not user:
        raise ApiError(
            404,
            "User Not Found",
            payload={"error": "User does not exist"},
        )

    blocked_until = _parse_datetime(user.get("blockTillLogInTimeStamp"))
    now_utc = datetime.now(timezone.utc)
    if blocked_until:
        if blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        if blocked_until > now_utc:
            raise ApiError(
                401,
                "Your account is blocked due to too many failed login attempts. Please wait and try again later.",
                payload={"error": "User is blocked"},
            )

    stored_password = user.get("password")
    if not stored_password or not verify_password(payload.password, stored_password):
        raise ApiError(
            401,
            "Incorrect password",
            payload={"error": "Incorrect password"},
        )

    device_info = {
        **_parse_user_agent(request.headers.get("user-agent", "")),
        "dateTimeAt": _get_now_iso(),
        "ip": request.client.host if request.client else None,
    }
    devices = user.get("devices") or []
    known_device = next(
        (
            device
            for device in devices
            if device.get("ip") == device_info["ip"] and device.get("browser") == device_info["browser"]
        ),
        None,
    )
    if not known_device:
        devices.append(device_info)
        await db["user"].update_one(
            {"_id": user["_id"]},
            {"$set": {"devices": devices}},
        )

    token_payload = {
        "authProvider": "MANUAL_LOGIN_MODE",
        "userName": user.get("userName"),
        "firstName": user.get("firstName"),
        "lastName": user.get("lastName"),
        "image": user.get("image"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "role": user.get("role", "user"),
        "clientName": request_context.client_name,
    }
    tokens = _generate_local_tokens(token_payload)

    response = success_response(
        payload={
            "authProvider": "login-web",
            "login_info": {
                "userFullName": user.get("userName"),
                "role": user.get("role", "user"),
                "image": user.get("image"),
                "email": user.get("email"),
                "phone": user.get("phone"),
                "firstName": user.get("firstName"),
                "lastName": user.get("lastName"),
            },
            "accessToken": tokens["access_token"],
        },
        message="Login successful",
    )
    _set_cookie(
        response,
        "refresh_token",
        tokens["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
    )
    _set_cookie(
        response,
        settings.session_cookie_name,
        tokens["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
        same_site="strict",
    )
    return response


@router.get("/me")
async def create_session(
    request: Request,
):
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise ApiError(401, "Session expired. Please login again.")

    try:
        device_id = request.headers.get("x-device-id")
        token_data = await oauth2_client.refresh_access_token(session_token, device_id, rotate=False)
        fresh_access_token = token_data["access_token"]
        user_info = await oauth2_client.get_user_info(fresh_access_token)
        response = success_response(
            payload={
                "authProvider": user_info.get("authProvider", "OAUTH"),
                "access_token": fresh_access_token,
                "login_info": user_info,
            },
            message="Session restored successfully",
        )
        if token_data.get("refresh_token") and token_data["refresh_token"] != session_token:
            refresh_exp = _parse_datetime(token_data.get("refresh_exp"))
            max_age = None
            if refresh_exp:
                if refresh_exp.tzinfo is None:
                    refresh_exp = refresh_exp.replace(tzinfo=timezone.utc)
                max_age = max(0, int((refresh_exp - datetime.now(timezone.utc)).total_seconds()))
            _set_cookie(
                response,
                settings.session_cookie_name,
                token_data["refresh_token"],
                max_age=max_age,
                same_site="strict",
            )
        return response
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401):
            raise ApiError(401, "Session expired. Please login again.") from exc
        raise ApiError(500, "Failed to restore session.") from exc
    except Exception as exc:
        raise ApiError(500, "Failed to restore session.") from exc


@router.get("/refresh")
async def refresh_token(
    request: Request,
):
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise ApiError(401, "Session expired. Please login again.")

    try:
        device_id = request.headers.get("x-device-id")
        token_data = await oauth2_client.refresh_access_token(session_token, device_id, rotate=False)
        response = success_response(
            payload={"access_token": token_data["access_token"]},
            message="Token refreshed",
        )
        if token_data.get("refresh_token") and token_data["refresh_token"] != session_token:
            refresh_exp = _parse_datetime(token_data.get("refresh_exp"))
            max_age = None
            if refresh_exp:
                if refresh_exp.tzinfo is None:
                    refresh_exp = refresh_exp.replace(tzinfo=timezone.utc)
                max_age = max(0, int((refresh_exp - datetime.now(timezone.utc)).total_seconds()))
            _set_cookie(
                response,
                settings.session_cookie_name,
                token_data["refresh_token"],
                max_age=max_age,
                same_site="strict",
            )
        return response
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401):
            raise ApiError(401, "Session expired. Please login again.") from exc
        raise ApiError(500, "Failed to refresh token.") from exc
    except Exception as exc:
        raise ApiError(500, "Failed to refresh token.") from exc


@router.post("/logout")
async def logout_user(
    request: Request,
    access_token: Optional[str] = Depends(extract_bearer_token),
):
    session_token = request.cookies.get(settings.session_cookie_name)

    try:
        if access_token and session_token:
            await oauth2_client.revoke_token(access_token, session_token)
        elif access_token:
            await oauth2_client.revoke_all_sessions(access_token)
    except Exception:
        pass

    response = success_response(
        payload={"logoutTime": _get_now_iso()},
        message="Logged out successfully",
    )
    _clear_cookie(response, settings.session_cookie_name, same_site="strict")
    _clear_cookie(response, "refresh_token")
    return response
