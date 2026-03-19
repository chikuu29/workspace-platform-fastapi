"""
Authentication Middleware — JWKS-based JWT validation via OpenID Configuration.

Validates every incoming request's Bearer token against the OAuth server's
public keys (JWKS). Public/whitelisted routes bypass authentication.

Flow:
  1. Extract Bearer token from Authorization header
  2. Validate JWT signature using JWKS from the OpenID discovery endpoint
  3. Store decoded token payload in `request.state.current_user`
  4. Return 401 for missing/invalid/expired tokens on protected routes
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logger import create_logger
from app.core.oauth2_client import oauth2_client

logger = create_logger(__name__)

# Routes that do NOT require authentication
# Use startswith matching so sub-paths are also allowed
PUBLIC_ROUTES: tuple[str, ...] = (
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/public/storage",
    "/api/v1/auth/",
    "/api/v1/oauth/",
)


def _is_public_route(path: str) -> bool:
    """Check if the request path is whitelisted for public access."""
    return any(path == route or path.startswith(route) for route in PUBLIC_ROUTES)


def _build_401_response(message: str = "Unauthorized") -> JSONResponse:
    """Construct a standardized 401 JSON response."""
    return JSONResponse(
        status_code=401,
        content={
            "success": False,
            "message": message,
        },
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWKS-based authentication middleware.

    - Validates Bearer tokens against the OAuth server's public keys
    - Injects decoded user payload into `request.state.current_user`
    - Skips validation for routes in PUBLIC_ROUTES
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        logger.debug("Processing request for path=%s", path)
        # Skip authentication for public routes
        if _is_public_route(path):
            return await call_next(request)

        # Extract Bearer token from Authorization header
        auth_header = request.headers.get("authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "Missing or malformed Authorization header for path=%s", path
            )
            return _build_401_response("Access token is required")

        access_token = auth_header[7:]  # Strip "Bearer " prefix
        print("access_token:", access_token)
        # Validate JWT against OAuth server's JWKS (public key)
        token_payload = await oauth2_client.validate_token(access_token)

        if token_payload is None:
            logger.warning("Token validation failed for path=%s", path)
            return _build_401_response("Access token expired or invalid")

        print(f"Authenticated user={token_payload.get('sub', 'unknown')} for path={path}")
        # Store validated user info in request state for downstream access
        request.state.current_user = token_payload
        request.state.access_token = access_token

        logger.debug(
            "Authenticated user=%s for path=%s",
            token_payload.get("sub", "unknown"),
            path,
        )

        return await call_next(request)
