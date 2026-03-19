from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from app.common.cookie import set_auth_cookie
from app.core.config import settings
from app.core.responses import success_response
from app.modules.auth.schemas import OAuthExchangeRequest
from app.modules.oauth.service import OAuthService
from app.modules.oauth.dependencies import get_oauth_service

router = APIRouter()


@router.get("/google")
async def start_google_login(
    redirectTo: str = Query("/", alias="redirectTo"),
    service: OAuthService = Depends(get_oauth_service),
):
    """Redirect user to Google OAuth consent screen."""
    url = service.get_google_auth_url(redirectTo)
    return RedirectResponse(url=url, status_code=307)


@router.get("/google/callback")
async def google_callback(
    code: str = Query(...),
    state: Optional[str] = Query(None),
    service: OAuthService = Depends(get_oauth_service),
):
    """Handle Google OAuth callback — exchange code for tokens."""
    result = await service.process_google_callback(code, state)

    redirect_response = RedirectResponse(url=result["redirect_to"], status_code=307)
    set_auth_cookie(
        redirect_response, "refresh_token", result["tokens"]["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS, same_site="lax",
    )
    set_auth_cookie(
        redirect_response, settings.session_cookie_name, result["tokens"]["refresh_token"],
        max_age=settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS,
    )
    return redirect_response


@router.post("/exchange")
async def oauth_exchange(
    payload: OAuthExchangeRequest,
    service: OAuthService = Depends(get_oauth_service),
):
    """Exchange an authorization code for OAuth tokens."""
    exchange_result = await service.exchange_code(payload)

    response = success_response(payload=exchange_result["payload"])

    if exchange_result.get("refresh_token"):
        set_auth_cookie(
            response, settings.session_cookie_name, exchange_result["refresh_token"],
            max_age=exchange_result["max_age"],
        )
    return response
