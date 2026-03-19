"""
Rate Limiting Middleware — Redis-backed sliding window rate limiter.

Protects critical authentication endpoints from brute-force attacks
and token endpoint abuse. Uses a sliding window counter stored in Redis.

Configurable via environment variables:
  - RATE_LIMIT_LOGIN: max attempts per window for /auth/login (default: 10)
  - RATE_LIMIT_TOKEN: max attempts per window for /oauth2/token (default: 20)
  - RATE_LIMIT_WINDOW: window size in seconds (default: 60)
"""

import os
from datetime import datetime, timezone
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.logger import setup_logger
from app.db.redis_store import redis_client

logger = setup_logger("rate_limiter")

# Rate limit configuration — configurable via env vars
RATE_LIMIT_LOGIN = int(os.getenv("RATE_LIMIT_LOGIN", "10"))
RATE_LIMIT_TOKEN = int(os.getenv("RATE_LIMIT_TOKEN", "20"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds

# Endpoint-specific limits: (path_prefix, max_requests)
RATE_LIMITED_PATHS = {
    "/auth/login": RATE_LIMIT_LOGIN,
    "/oauth2/token": RATE_LIMIT_TOKEN,
}


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For behind reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-backed sliding window rate limiter for critical endpoints.
    
    Uses a simple counter with TTL expiry in Redis.
    Non-rate-limited paths pass through with zero overhead.
    """

    async def dispatch(self, request: Request, call_next):
        """Check rate limits for protected endpoints before dispatching."""
        path = request.url.path
        
        # Only apply to rate-limited paths
        limit = None
        for protected_path, max_requests in RATE_LIMITED_PATHS.items():
            if path.startswith(protected_path):
                limit = max_requests
                break

        if limit is None:
            return await call_next(request)

        client_ip = _get_client_ip(request)
        rate_key = f"ratelimit:{path}:{client_ip}"

        ttl = RATE_LIMIT_WINDOW
        current_count = 0
        
        try:
            redis = redis_client.get_client()
            current_count = await redis.incr(rate_key)

            # Set TTL only on the first request in the window
            if current_count == 1:
                await redis.expire(rate_key, RATE_LIMIT_WINDOW)

            # Get remaining TTL for headers
            ttl = await redis.ttl(rate_key)

            if current_count > limit:
                logger.warning(
                    "Rate limit exceeded: ip=%s path=%s count=%d limit=%d",
                    client_ip, path, current_count, limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "error_description": f"Too many requests. Retry after {ttl} seconds.",
                        "retry_after": ttl,
                    },
                    headers={
                        "Retry-After": str(ttl),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(ttl),
                    },
                )

        except Exception as e:
            # If Redis is down, log it but continue processing (fail-open)
            logger.error("Rate limiter Redis error: %s — failing open", str(e))
            # current_count stays 0 or within limit, allowing the request through

        response = await call_next(request)
        
        # Add rate limit headers to successful responses (if we have valid count/ttl)
        if current_count > 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current_count))
            response.headers["X-RateLimit-Reset"] = str(ttl)
            
        return response
