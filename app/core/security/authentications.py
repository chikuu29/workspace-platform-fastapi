import logging
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, Request, Cookie
from fastapi import status
from typing import Annotated, Optional
from app.core.oauth2_client import oauth2_client
from app.core.logger import create_logger



logger = create_logger(__name__)
security = HTTPBearer()

async def _resolve_payload(payload: dict) -> dict:
    """Normalize payload: check audience and resolve user_name."""
    if payload.get("aud") == "self":
        scopes = payload.get("scope", [])
        if isinstance(scopes, str):
            scopes = scopes.split()
        
        standard_scopes = ["openid", "profile", "email", "roles"]
        for s in standard_scopes:
            if s not in scopes:
                scopes.append(s)
        payload["scope"] = scopes

    identity = payload.get("identity") or payload
    username = identity.get("sub") or identity.get("username")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim"
        )
    # Don't destructively modify if it's already structured, but set it for convenience
    if "identity" in payload:
        payload["identity"]["username"] = username
    else:
        payload["username"] = username
    return payload


async def get_authenticated_identity(
    request: Request,
    auth: HTTPAuthorizationCredentials = Depends(security),
    
) -> dict:
    """
    Unified dependency that extracts, validates, and enriches the user identity.
    Implementation includes Redis-based caching to minimize DB hits.
    """
    token = auth.credentials
    try:
        # 1. Validate Token (Fast JWT check)
        payload = await oauth2_client.validate_token(token=token)
        print("Token validated, payload:", payload)
        # payload = await _resolve_payload(payload)
        request.state.user = payload
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


async def get_user_identity(identity: dict = Depends(get_authenticated_identity)):
    """Legacy wrapper/fallback for get_authenticated_identity."""
    return identity


# async def get_session_identity(
#     request: Request,
#     refresh_token: Annotated[Optional[str], Cookie()] = None,
#     db: AsyncSession = Depends(get_db),
# ) -> Optional[dict]:
#     """
#     Authenticate via httpOnly refresh_token cookie (Single Sign-On).
#     Used primarily by the /authorize endpoint to recognize already logged-in users.
#     """

#     if not refresh_token:
#         return None

#     try:
#         device_info = extract_device_fingerprint(request)
#         device_id = device_info.get("device_id")
        
#         # Validate existing session without rotating (don't burn the cookie during authorize)
#         validation = await validate_and_rotate_refresh_token(
#             db=db,
#             raw_token=refresh_token,
#             device_fingerprint=device_info,
#             rotate=False
#         )
        
#         # Load user to build payload
#         result = await db.execute(
#             select(User)
#             .options(
#                 selectinload(User.profile),
#                 selectinload(User.organization),
#                 selectinload(User.roles).selectinload(Role.policies)
#             )
#             .filter(User.id == validation["user_id"])
#         )
#         user = result.scalars().first()
#         if not user:
#             return None
        
#         # Check cache first
#         cached_identity = await redis_client.get_identity_cache(user.username, 'self', device_id)
#         if cached_identity:
#             return await _resolve_payload(cached_identity)

#         # Re-hydrate full authorization context
#         account_service = AccountService(db, organization_uuid=user.organization.organization_uuid)
#         auth_context = await account_service.build_account_authorization_context(user=user)
        
#         payload = AuthService.build_user_auth_payload(auth_context)
        
#         # Cache the re-hydrated identity
#         await redis_client.set_identity_cache(user.username, 'self', device_id, payload)
        
#         return await _resolve_payload(payload)

#     except Exception as e:
#         logger.warning(f"Session authentication failed: {str(e)}")
#         return None
