from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import extract_bearer_token, require_request_context
from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client
from app.core.responses import success_response
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import AuthService
from app.modules.auth.dependencies import get_auth_service

router = APIRouter()

def _set_cookie(response: Response, key: str, value: str, *, max_age: Optional[int] = None, same_site: str = "lax") -> None:
    response.set_cookie(
        key=key, value=value, httponly=True, secure=settings.is_production, samesite=same_site, path="/", max_age=max_age
    )

def _clear_cookie(response: Response, key: str, *, same_site: str = "lax") -> None:
    response.delete_cookie(
        key=key, httponly=True, secure=settings.is_production, samesite=same_site, path="/"
    )

@router.post("/register")
async def register_user(
    payload: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
    request_context=Depends(require_request_context),
):
    response_data = await service.register(payload)
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
    service: AuthService = Depends(get_auth_service),
    request_context=Depends(require_request_context),
):
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")
    
    login_result = await service.login(payload, ip, user_agent, request_context.client_name)
    user = login_result["user"]
    tokens = login_result["tokens"]

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
    
    _set_cookie(response, "refresh_token", tokens["refresh_token"], max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS)
    _set_cookie(response, settings.session_cookie_name, tokens["refresh_token"], max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS, same_site="strict")
    return response

@router.get("/me")
async def create_session(request: Request, service: AuthService = Depends(get_auth_service)):
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise ApiError(401, "Session expired. Please login again.")

    try:
        device_id = request.headers.get("x-device-id")
        token_data = await oauth2_client.refresh_access_token(session_token, device_id, rotate=False)
        fresh_access_token = token_data["access_token"]
        user_info = await oauth2_client.get_user_info(fresh_access_token)
        
        response = success_response(
            payload={"authProvider": user_info.get("authProvider", "OAUTH"), "access_token": fresh_access_token, "login_info": user_info},
            message="Session restored successfully",
        )
        
        if token_data.get("refresh_token") and token_data["refresh_token"] != session_token:
            refresh_exp = service.parse_datetime(token_data.get("refresh_exp"))
            max_age = None
            if refresh_exp:
                if refresh_exp.tzinfo is None:
                    refresh_exp = refresh_exp.replace(tzinfo=timezone.utc)
                max_age = max(0, int((refresh_exp - datetime.now(timezone.utc)).total_seconds()))
            _set_cookie(response, settings.session_cookie_name, token_data["refresh_token"], max_age=max_age, same_site="strict")
        return response
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401):
            raise ApiError(401, "Session expired. Please login again.") from exc
        raise ApiError(500, "Failed to restore session.") from exc
    except Exception as exc:
        raise ApiError(500, "Failed to restore session.") from exc

@router.get("/refresh")
async def refresh_token(request: Request, service: AuthService = Depends(get_auth_service)):
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise ApiError(401, "Session expired. Please login again.")

    try:
        device_id = request.headers.get("x-device-id")
        token_data = await oauth2_client.refresh_access_token(session_token, device_id, rotate=False)
        response = success_response(payload={"access_token": token_data["access_token"]}, message="Token refreshed")
        
        if token_data.get("refresh_token") and token_data["refresh_token"] != session_token:
            refresh_exp = service.parse_datetime(token_data.get("refresh_exp"))
            max_age = None
            if refresh_exp:
                if refresh_exp.tzinfo is None:
                    refresh_exp = refresh_exp.replace(tzinfo=timezone.utc)
                max_age = max(0, int((refresh_exp - datetime.now(timezone.utc)).total_seconds()))
            _set_cookie(response, settings.session_cookie_name, token_data["refresh_token"], max_age=max_age, same_site="strict")
        return response
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401):
            raise ApiError(401, "Session expired. Please login again.") from exc
        raise ApiError(500, "Failed to refresh token.") from exc
    except Exception as exc:
        raise ApiError(500, "Failed to refresh token.") from exc

@router.post("/logout")
async def logout_user(request: Request, access_token: Optional[str] = Depends(extract_bearer_token)):
    session_token = request.cookies.get(settings.session_cookie_name)
    try:
        if access_token and session_token: await oauth2_client.revoke_token(access_token, session_token)
        elif access_token: await oauth2_client.revoke_all_sessions(access_token)
    except Exception:
        pass

    response = success_response(payload={"logoutTime": datetime.now(timezone.utc).isoformat()}, message="Logged out successfully")
    _clear_cookie(response, settings.session_cookie_name, same_site="strict")
    _clear_cookie(response, "refresh_token")
    return response
