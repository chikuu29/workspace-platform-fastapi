"""
API Response Helpers — consistent, structured response shapes.

Every endpoint in the workspace backend should use these helpers
to guarantee a predictable contract for frontend consumers:

    Success → { "success": True,  "message": "...", "data": {...} }
    Error   → { "success": False, "message": "...", "error_code": "..." }

Usage:
    from app.common.responses import ok, created, paginated, conflict

    return ok(data=doc, message="Member loaded")
    return created(data=result, message="Member registered")
    return paginated(data=docs, total=100, skip=0, limit=50)
    raise conflict("DUPLICATE_MEMBER", "A member with this email already exists.", details={...})
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException


# ── Success Responses ────────────────────────────────────────────────


def ok(
    *,
    data: Any = None,
    message: str = "Request completed successfully.",
) -> Dict[str, Any]:
    """Standard 200 OK response."""
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def created(
    *,
    data: Any = None,
    message: str = "Resource created successfully.",
) -> Dict[str, Any]:
    """Response for successful resource creation (POST)."""
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def paginated(
    *,
    data: List[Any],
    total: int,
    skip: int,
    limit: int,
    message: str = "Records retrieved successfully.",
) -> Dict[str, Any]:
    """Paginated list response with total count and offset metadata."""
    return {
        "success": True,
        "message": message,
        "data": data,
        "pagination": {
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + limit) < total,
        },
    }


def deleted(
    *,
    message: str = "Record deleted successfully.",
) -> Dict[str, Any]:
    """Response for successful soft-delete."""
    return {
        "success": True,
        "message": message,
    }


# ── Error Helpers ────────────────────────────────────────────────────
# These raise HTTPException so the caller doesn't need to import it.
#
# Response shape:
#   { "success": false, "message": "Human-readable text", "details": { "error_code": "...", ... } }
#
# `message`  → always a plain, UI-safe string the frontend can display directly.
# `details`  → machine-readable bag with error_code + any extra context.


def not_found(
    message: str = "Resource not found.",
    error_code: str = "NOT_FOUND",
) -> None:
    """Raise a 404 HTTPException with a structured detail body."""
    raise HTTPException(
        status_code=404,
        detail={
            "success": False,
            "message": message,
            "details": {"error_code": error_code},
        },
    )


def bad_request(
    message: str = "Invalid request.",
    error_code: str = "BAD_REQUEST",
) -> None:
    """Raise a 400 HTTPException with a structured detail body."""
    raise HTTPException(
        status_code=400,
        detail={
            "success": False,
            "message": message,
            "details": {"error_code": error_code},
        },
    )


def conflict(
    message: str = "Resource already exists.",
    error_code: str = "CONFLICT",
    *,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise a 409 HTTPException for duplicate/conflict scenarios."""
    merged_details: Dict[str, Any] = {"error_code": error_code}
    if details:
        merged_details.update(details)

    raise HTTPException(
        status_code=409,
        detail={
            "success": False,
            "message": message,
            "details": merged_details,
        },
    )

