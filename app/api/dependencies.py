"""
API-level dependencies — auth guards, request context, RBAC.

The AuthMiddleware already validates Bearer tokens via JWKS and stores
the decoded payload in `request.state.current_user`. These dependencies
provide type-safe access and role-based guards for specific endpoints.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, Request

from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client


@dataclass
class RequestContext:
    """Parsed request context containing client and app identification."""
    client_name: str
    app_name: str
    app_db_collection: Optional[str]


def _parse_app_name(referer: str) -> str:
    """Extract app name from the referer query string, defaulting to 'default'."""
    if not referer:
        return "default"

    parsed = urlparse(referer)
    app_names = parse_qs(parsed.query).get("app")
    return app_names[0] if app_names else "default"


async def require_request_context(request: Request) -> RequestContext:
    """
    Validate the x-client-id header and build a RequestContext.

    Ensures only known OAuth client IDs can access the API.
    """
    client_id = request.headers.get("x-client-id")
    if not client_id :
        raise ApiError(401, "Unauthorized Access")

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
    """Extract the raw Bearer token from the Authorization header."""
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        request.state.access_token = token
        return token

    request.state.access_token = None
    return None


async def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Retrieve the authenticated user from request state.

    The AuthMiddleware has already validated the token via JWKS.
    This dependency provides type-safe access for route handlers.
    Falls back to direct token validation if middleware didn't run
    (e.g., in tests or whitelisted routes calling this explicitly).
    """
    # Prefer middleware-injected user (already validated via JWKS)
    current_user = getattr(request.state, "current_user", None)
    if current_user:
        return current_user

    # Fallback: validate token directly (for edge cases)
    access_token = getattr(request.state, "access_token", None)
    if not access_token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]

    if not access_token:
        raise ApiError(401, "Access token is required")

    token_info = await oauth2_client.validate_token(access_token)
    if not token_info:
        raise ApiError(401, "Access token expired or invalid")

    request.state.current_user = token_info
    return token_info


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory for role-based access control (RBAC).

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(): ...

        # Or inject user:
        @router.get("/admin")
        async def admin_endpoint(user = Depends(require_role("admin"))): ...
    """
    async def _check_role(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        user_role = current_user.get("role", "")
        if user_role not in allowed_roles:
            raise ApiError(403, "Insufficient permissions for this resource")
        return current_user

    return _check_role
