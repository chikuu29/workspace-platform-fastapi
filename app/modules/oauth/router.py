import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client
from app.core.responses import success_response
from app.db.database import get_database
from app.modules.auth.schemas import OAuthExchangeRequest

router = APIRouter()


def _generate_local_tokens(payload: Dict[str, Any]) -> Dict[str, str]:
    issued_at = int(datetime.now(timezone.utc).timestamp())
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
    response,
    key: str,
    value: str,
    *,
    max_age: Optional[int] = None,
    same_site: str = "strict",
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


def _parse_expiry_seconds(refresh_exp: Optional[str]) -> Optional[int]:
    if not refresh_exp:
        return None
    normalized = refresh_exp.replace("Z", "+00:00")
    try:
        refresh_datetime = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if refresh_datetime.tzinfo is None:
        refresh_datetime = refresh_datetime.replace(tzinfo=timezone.utc)
    return max(0, int((refresh_datetime - datetime.now(timezone.utc)).total_seconds()))


@router.get("/google")
async def start_google_login(redirectTo: str = Query("/", alias="redirectTo")):
    if not settings.GOOGLE_CLIENT_ID:
        raise ApiError(503, "Google OAuth is not configured.")

    query = urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_CALLBACK_URL,
            "response_type": "code",
            "scope": "openid email profile",
            "state": json.dumps({"redirectTo": redirectTo}),
        }
    )
    return RedirectResponse(url=f"{settings.GOOGLE_AUTH_URL}?{query}", status_code=307)


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ApiError(503, "Google OAuth is not configured.")

    redirect_to = "/"
    if state:
        try:
            redirect_to = json.loads(state).get("redirectTo", "/")
        except json.JSONDecodeError:
            redirect_to = "/"

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            settings.GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.GOOGLE_OAUTH_CALLBACK_URL,
            },
        )
        token_response.raise_for_status()
        google_tokens = token_response.json()

        userinfo_response = await client.get(
            settings.GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_tokens['access_token']}"},
        )
        userinfo_response.raise_for_status()
        oauth_data = userinfo_response.json()

    if not oauth_data.get("email_verified"):
        raise ApiError(400, "Google account email is not verified.")

    stored_user = await db["user"].find_one({"email": oauth_data["email"]})
    oauth_snapshot = {
        "oauth": {
            "GoogleOauth": {
                **oauth_data,
                "dateTimeAt": datetime.now(timezone.utc).isoformat(),
            }
        }
    }

    if stored_user:
        await db["user"].update_one(
            {"_id": stored_user["_id"]},
            {"$set": {**oauth_snapshot, "image": oauth_data.get("picture")}},
        )
        phone = stored_user.get("phone")
    else:
        phone = None
        await db["user"].insert_one(
            {
                "registerMode": "OAUTH",
                "role": "user",
                "image": oauth_data.get("picture"),
                "userName": oauth_data.get("name"),
                "email": oauth_data.get("email"),
                "phone": phone,
                "firstName": oauth_data.get("given_name"),
                "lastName": oauth_data.get("family_name"),
                "address": None,
                **oauth_snapshot,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )

    tokens = _generate_local_tokens(
        {
            "authProvider": "GOOGLE_OAUTH_MODE",
            "userName": oauth_data.get("name"),
            "firstName": oauth_data.get("given_name"),
            "lastName": oauth_data.get("family_name"),
            "image": oauth_data.get("picture"),
            "email": oauth_data.get("email"),
            "phone": phone,
            "role": "user",
        }
    )

    redirect_response = RedirectResponse(url=redirect_to, status_code=307)
    _set_cookie(
        redirect_response,
        "refresh_token",
        tokens["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
        same_site="lax",
    )
    _set_cookie(
        redirect_response,
        settings.session_cookie_name,
        tokens["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
    )
    return redirect_response


@router.post("/exchange")
async def oauth_exchange(payload: OAuthExchangeRequest):
    try:
        token_data = await oauth2_client.exchange_code(
            code=payload.code,
            redirect_url=payload.redirect_url,
            device_id=payload.device_id,
            code_verifier=payload.code_verifier,
        )
        user_info = await oauth2_client.get_user_info(token_data["access_token"])

        response = success_response(
            payload={
                **token_data,
                "authProvider": user_info.get("authProvider", "OAUTH"),
                "login_info": user_info,
            }
        )
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            _set_cookie(
                response,
                settings.session_cookie_name,
                refresh_token,
                max_age=_parse_expiry_seconds(token_data.get("refresh_exp")),
            )
        return response
    except httpx.HTTPStatusError as exc:
        raise ApiError(
            exc.response.status_code,
            "Error from OAuth server",
            payload={"error": exc.response.text},
        ) from exc
    except Exception as exc:
        raise ApiError(500, "Request failed", payload={"error": str(exc)}) from exc
