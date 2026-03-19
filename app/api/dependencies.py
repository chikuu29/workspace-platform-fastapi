from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, Request

from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client


@dataclass
class RequestContext:
    client_name: str
    app_name: str
    app_db_collection: Optional[str]


def _parse_app_name(referer: str) -> str:
    if not referer:
        return "defult"

    parsed = urlparse(referer)
    app_names = parse_qs(parsed.query).get("app")
    return app_names[0] if app_names else "defult"


async def require_request_context(request: Request) -> RequestContext:
    client_id = request.headers.get("x-client-id")
    if not client_id or client_id not in settings.allowed_client_ids:
        raise ApiError(401, "Unautorization Access")

    app_name = _parse_app_name(request.headers.get("referer", ""))
    context = RequestContext(
        client_name=client_id,
        app_name=app_name,
        app_db_collection=settings.APP_COLLECTION_MAP.get(app_name),
    )

    request.state.client_name = context.client_name
    request.state.app_name = context.app_name
    request.state.app_db_collection = context.app_db_collection
    return context


async def extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        request.state.access_token = token
        return token

    request.state.access_token = None
    return None


async def get_current_user(
    request: Request,
    access_token: Optional[str] = Depends(extract_bearer_token),
) -> Dict[str, Any]:
    if not access_token:
        raise ApiError(401, "Access token is required")

    token_info = await oauth2_client.validate_token(access_token)
    if not token_info:
        raise ApiError(401, "Access token expired or invalid")

    request.state.token_info = token_info
    return token_info
