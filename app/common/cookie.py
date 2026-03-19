"""
Shared HTTP cookie utilities for authentication responses.

Extracted from auth/router.py and oauth/router.py to eliminate duplication.
Both modules now import from here.
"""

from typing import Optional

from fastapi import Response

from app.core.config import settings


def set_auth_cookie(
    response: Response,
    key: str,
    value: str,
    *,
    max_age: Optional[int] = None,
    same_site: str = "strict",
) -> None:
    """Set an httpOnly, secure (in prod) authentication cookie."""
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=settings.is_production,
        samesite=same_site,
        path="/",
        max_age=max_age,
    )


def clear_auth_cookie(
    response: Response,
    key: str,
    *,
    same_site: str = "strict",
) -> None:
    """Clear an authentication cookie."""
    response.delete_cookie(
        key=key,
        httponly=True,
        secure=settings.is_production,
        samesite=same_site,
        path="/",
    )
