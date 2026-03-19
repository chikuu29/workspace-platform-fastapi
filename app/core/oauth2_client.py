import time
import logging
from typing import Dict, Any, List, Optional
import httpx
from jose import jwt, JWTError

from app.core.config import settings

logger = logging.getLogger(__name__)

class OAuth2Client:
    """
    OAuth2Client — Centralized OAuth2 server communication service.

    Responsibilities:
     1. Cache the OpenID discovery document (avoids hitting /.well-known on every request)
     2. Cache JWKS keys for token validation
     3. Exchange authorization codes for tokens
     4. Refresh access tokens via refresh_token grant
     5. Fetch user info from the userinfo endpoint
     6. Validate JWTs using the OAuth2 server's JWKS
    """

    def __init__(self) -> None:
        """Initialize the OAuth2 Client with TTL caching properties."""
        self._discovery_cache: Optional[Dict[str, Any]] = None
        self._discovery_cached_at: float = 0.0

        self._jwks_cache: Optional[List[Dict[str, Any]]] = None
        self._jwks_cached_at: float = 0.0

        # TTL for caches in seconds (10 minutes)
        self._cache_ttl: float = 10 * 60.0

    async def get_discovery(self) -> Dict[str, Any]:
        """
        Fetch and cache the OpenID Connect discovery document.
        Returns cached version if within TTL.
        """
        now = time.time()
        if self._discovery_cache and (now - self._discovery_cached_at) < self._cache_ttl:
            return self._discovery_cache

        if not settings.OAUTH_OPENID_CONFIG_URL:
            raise ValueError("OAUTH_OPENID_CONFIG_URL is not set in environment variables.")

        async with httpx.AsyncClient() as client:
            response = await client.get(settings.OAUTH_OPENID_CONFIG_URL)
            response.raise_for_status()
            self._discovery_cache = response.json()
            self._discovery_cached_at = now

        return self._discovery_cache

    async def get_jwks(self) -> List[Dict[str, Any]]:
        """
        Fetch and cache JWKS (JSON Web Key Set) from the OAuth2 server.
        Used for validating JWT signatures.
        """
        now = time.time()
        if self._jwks_cache and (now - self._jwks_cached_at) < self._cache_ttl:
            return self._jwks_cache

        discovery = await self.get_discovery()
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise ValueError("jwks_uri not found in OpenID discovery document.")

        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            self._jwks_cache = response.json().get("keys", [])
            self._jwks_cached_at = now

        return self._jwks_cache

    def clear_cache(self) -> None:
        """Invalidate all caches. Useful when a key rotation is detected."""
        self._discovery_cache = None
        self._discovery_cached_at = 0.0
        self._jwks_cache = None
        self._jwks_cached_at = 0.0

    async def exchange_code(
        self, code: str, redirect_url: str, device_id: str, code_verifier: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Exchange an authorization code for tokens (authorization_code grant).
        """
        discovery = await self.get_discovery()
        token_url = settings.OAUTH_TOKEN_URI or discovery.get("token_endpoint")
        
        if not token_url:
            raise ValueError("token_endpoint not found in discovery and OAUTH_TOKEN_URI is empty.")

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_url": redirect_url,
            "device_id": device_id,
            "client_id": settings.OAUTH_CLIENT_ID,
            "client_secret": settings.OAUTH_CLIENT_SECRET,
        }

        if code_verifier:
            payload["code_verifier"] = code_verifier

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def refresh_access_token(
        self, refresh_token: str, device_id: Optional[str] = None, rotate: bool = True
    ) -> Dict[str, Any]:
        """
        Refresh the access token using a refresh_token grant.
        """
        discovery = await self.get_discovery()
        token_url = settings.OAUTH_TOKEN_URI or discovery.get("token_endpoint")
        
        if not token_url:
            raise ValueError("token_endpoint not found in discovery and OAUTH_TOKEN_URI is empty.")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.OAUTH_CLIENT_ID,
            "client_secret": settings.OAUTH_CLIENT_SECRET,
            "rotate": rotate,
        }

        if device_id:
            payload["device_id"] = device_id

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Fetch the authenticated user's profile from the OAuth2 server's userinfo endpoint.
        """
        discovery = await self.get_discovery()
        userinfo_url = discovery.get("userinfo_endpoint")

        if not userinfo_url:
            raise ValueError("userinfo_endpoint not found in OpenID discovery document.")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a JWT against the OAuth2 server's JWKS.
        """
        try:
            jwks = await self.get_jwks()

            unverified_header = jwt.get_unverified_header(token)
            if not unverified_header:
                raise ValueError("Unable to decode JWT header.")

            kid = unverified_header.get("kid")
            if not kid:
                raise ValueError("JWT header lacks a key id (kid).")

            jwk = next((key for key in jwks if key.get("kid") == kid), None)

            if not jwk:
                # JWKS might have rotated, force refetch once
                self._jwks_cache = None
                fresh_jwks = await self.get_jwks()
                jwk = next((key for key in fresh_jwks if key.get("kid") == kid), None)

            if not jwk:
                raise ValueError(f"No matching JWK found for kid: {kid}")

            payload = jwt.decode(
                token,
                jwk,
                algorithms=["RS256"],
                audience=settings.OAUTH_CLIENT_ID,
                options={"verify_aud": False}  # Configure based on actual requirements
            )

            return payload
        except JWTError as e:
            logger.error(f"❌ Token validation failed (JWTError): {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Token validation failed: {e}")
            return None

    def _get_auth_server_base(self) -> str:
        """
        Derive the Auth Server base URL from the OpenID discovery URL.
        """
        return settings.OAUTH_OPENID_CONFIG_URL.replace("/.well-known/openid-configuration", "")

    async def revoke_token(self, access_token: str, refresh_token: str) -> Dict[str, Any]:
        """
        Revoke a specific refresh token on the OAuth2 server.
        """
        revoke_url = f"{self._get_auth_server_base()}/oauth2/revoke"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                revoke_url,
                json={"token": refresh_token},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()

    async def revoke_all_sessions(self, access_token: str) -> Dict[str, Any]:
        """
        Revoke ALL sessions for the current user+client on the OAuth2 server.
        """
        revoke_url = f"{self._get_auth_server_base()}/oauth2/revoke"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                revoke_url,
                json={"revoke_all": True},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()

# Singleton instance
oauth2_client = OAuth2Client()
