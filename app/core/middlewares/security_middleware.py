from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        # 🔹 Get all relevant headers dynamically
        filtered_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower().startswith("x-") or key.lower() == "referer"
        }

        # 🔹 Attach to request.state
        request.state.security_headers = filtered_headers

        # Continue request
        response = await call_next(request)

        # 🔹 Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"

        return response