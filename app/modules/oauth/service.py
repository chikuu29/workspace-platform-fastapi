import json
from datetime import datetime, timezone
import time
from typing import Dict, Any, Optional
from urllib.parse import urlencode
import httpx
import jwt

from app.core.config import settings
from app.core.errors import ApiError
from app.core.oauth2_client import oauth2_client
from app.modules.oauth.repository import OAuthRepository
from app.modules.auth.schemas import OAuthExchangeRequest
from app.core.logger import create_logger

class OAuthService:
    def __init__(self, repository: OAuthRepository):
        self.repository = repository
        self.logger = create_logger("oauth_service")

    def _generate_local_tokens(self, payload: Dict[str, Any]) -> Dict[str, str]:
        issued_at = int(datetime.now(timezone.utc).timestamp())
        access_token = jwt.encode(
            {**payload, "exp": issued_at + settings.LOCAL_ACCESS_TOKEN_EXPIRE_SECONDS, "iat": issued_at},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        refresh_token = jwt.encode(
            {**payload, "exp": issued_at + settings.LOCAL_REFRESH_TOKEN_EXPIRE_SECONDS, "iat": issued_at},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        return {"access_token": access_token, "refresh_token": refresh_token}

    def _parse_expiry_seconds(self, refresh_exp: Optional[str]) -> Optional[int]:
        if not refresh_exp: return None
        normalized = refresh_exp.replace("Z", "+00:00")
        try: refresh_datetime = datetime.fromisoformat(normalized)
        except ValueError: return None
        if refresh_datetime.tzinfo is None: refresh_datetime = refresh_datetime.replace(tzinfo=timezone.utc)
        return max(0, int((refresh_datetime - datetime.now(timezone.utc)).total_seconds()))

    def get_google_auth_url(self, redirect_to: str) -> str:
        self.logger.info(f"Generating Google OAuth URL with redirect_to={redirect_to}")
        if not settings.GOOGLE_CLIENT_ID:
            self.logger.error("Google OAuth client ID is missing")
            raise ApiError(503, "Google OAuth is not configured.")
        query = urlencode({
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_CALLBACK_URL,
            "response_type": "code",
            "scope": "openid email profile",
            "state": json.dumps({"redirectTo": redirect_to}),
        })
        return f"{settings.GOOGLE_AUTH_URL}?{query}"

    async def process_google_callback(self, code: str, state: Optional[str]) -> Dict[str, Any]:
        self.logger.info("Processing Google OAuth callback")
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            self.logger.error("Google OAuth secrets are missing")
            raise ApiError(503, "Google OAuth is not configured.")

        redirect_to = "/"
        if state:
            try: redirect_to = json.loads(state).get("redirectTo", "/")
            except json.JSONDecodeError: redirect_to = "/"

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
            self.logger.warning("Google account email is not verified for OAuth login")
            raise ApiError(400, "Google account email is not verified.")

        self.logger.info(f"Google OAuth verified for email: {oauth_data['email']}")

        stored_user = await self.repository.find_user_by_email(oauth_data["email"])
        oauth_snapshot = {
            "oauth": {
                "GoogleOauth": {
                    **oauth_data,
                    "dateTimeAt": datetime.now(timezone.utc).isoformat(),
                }
            }
        }

        if stored_user:
            await self.repository.update_user_oauth(stored_user["_id"], oauth_snapshot, oauth_data.get("picture"))
            phone = stored_user.get("phone")
        else:
            phone = None
            await self.repository.create_oauth_user({
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
            })

        tokens = self._generate_local_tokens({
            "authProvider": "GOOGLE_OAUTH_MODE",
            "userName": oauth_data.get("name"),
            "firstName": oauth_data.get("given_name"),
            "lastName": oauth_data.get("family_name"),
            "image": oauth_data.get("picture"),
            "email": oauth_data.get("email"),
            "phone": phone,
            "role": "user",
        })

        return {"redirect_to": redirect_to, "tokens": tokens}

    async def exchange_code(self, payload: OAuthExchangeRequest) -> Dict[str, Any]:
        self.logger.info("Exchanging generic OAuth code")
        try:
            token_data = await oauth2_client.exchange_code(
                code=payload.code,
                redirect_url=payload.redirect_url,
                device_id=payload.device_id,
                code_verifier=payload.code_verifier,
            )
            user_info = await oauth2_client.get_user_info(token_data["access_token"])
            
            return {
                "payload": {
                    **token_data,
                    "authProvider": user_info.get("authProvider", "OAUTH"),
                    "login_info": user_info,
                },
                "refresh_token": token_data.get("refresh_token"),
                "max_age": self._parse_expiry_seconds(token_data.get("refresh_exp"))
            }
            
        except httpx.HTTPStatusError as exc:
            self.logger.error(f"OAuth server error during exchange: {exc.response.text}")
            raise ApiError(exc.response.status_code, "Error from OAuth server", payload={"error": exc.response.text}) from exc
        except Exception as exc:
            self.logger.error(f"Failed to exchange OAuth code: {str(exc)}")
            raise ApiError(500, "Request failed", payload={"error": str(exc)}) from exc
