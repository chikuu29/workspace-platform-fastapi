"""
Organization Context — secure, JWT-derived request context.

OrgContext is the SINGLE source of truth for "who is making this request"
and "which organization do they belong to". It is extracted from the
already-validated JWT claims (request.state.user) and the security headers
set by SecurityMiddleware — never from the request body.

The app_id is read from the `x-app-code` header that the frontend sends
on every request.

Usage:
    from app.core.context import OrgContext, get_org_context

    @router.post("/members")
    async def add_member(
        ctx: OrgContext = Depends(get_org_context),
    ):
        print(ctx.org_id, ctx.app_code, ctx.user_id)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Header, Request, status

from app.core.security.authentications import get_authenticated_identity


@dataclass(frozen=True, slots=True)
class OrgContext:
    """
    Immutable organization + user context for the current request.

    Frozen dataclass ensures no downstream code can accidentally mutate
    the org_id or user identity mid-request.
    """

    # ── Organization ─────────────────────────────────────────────────
    org_id: int
    org_uuid: str
    org_name: str

    # ── User ─────────────────────────────────────────────────────────
    user_id: str  # JWT 'sub' claim
    user_name: str
    user_type: str

    # ── App Context ──────────────────────────────────────────────────
    app_code: str  # From x-app-code header (e.g. "myGym")
    app_name: str  # Display name (defaults to app_code)
    subscribed_apps: List[str] = field(default_factory=list)

    # ── Raw JWT (for edge cases) ─────────────────────────────────────
    raw_claims: Dict[str, Any] = field(default_factory=dict, repr=False)

    # ── Builders for Document Stamps ─────────────────────────────────

    def to_org_block(self) -> Dict[str, Any]:
        """
        Generates the `_org` block stamped on every document.

        This block is IMMUTABLE after insert — it records which org
        and app created this document.
        """
        return {
            "org_id": self.org_id,
            "org_uuid": self.org_uuid,
            "org_name": self.org_name,
            "app_code": self.app_code,
            "app_name": self.app_name,
        }

    def to_created_meta(self, entity_type: str, record_id: str) -> Dict[str, Any]:
        """Generates the `_meta` block for a new document."""
        now = datetime.now(timezone.utc)
        return {
            "entity_type": entity_type,
            "record_id": record_id,
            "version": 1,
            "is_deleted": False,
            "created": {"at": now, "by": self.user_id},
            "updated": {"at": now, "by": self.user_id},
            "deleted": None,
        }

    def to_update_meta(self) -> Dict[str, Any]:
        """Generates `$set` fields for the `_meta` block on update."""
        return {
            "_meta.updated.at": datetime.now(timezone.utc),
            "_meta.updated.by": self.user_id,
        }

    def to_delete_meta(self) -> Dict[str, Any]:
        """Generates `$set` fields for soft-delete."""
        now = datetime.now(timezone.utc)
        return {
            "_meta.is_deleted": True,
            "_meta.deleted": {"at": now, "by": self.user_id},
            "_meta.updated.at": now,
            "_meta.updated.by": self.user_id,
        }

    @property
    def org_filter(self) -> Dict[str, Any]:
        """Standard MongoDB filter to scope queries to this org."""
        return {"_org.org_id": self.org_id}

    @property
    def active_filter(self) -> Dict[str, Any]:
        """Filter for non-deleted documents within this org."""
        return {
            "_org.org_id": self.org_id,
            "_meta.is_deleted": False,
        }


# ── FastAPI Dependency ───────────────────────────────────────────────────


async def get_org_context(
    request: Request,
    _: dict = Depends(get_authenticated_identity),
    x_app_code:str = Header(..., alias="X-App-Code")  # For explicit header extraction (alternative to middleware)
) -> OrgContext:
    """
    Resolve OrgContext from JWT claims + security headers.

    - org_id, org_uuid, user_id → from JWT (request.state.user)
    - app_id → from x-app-code header (request.state.security_headers)

    This is a single dependency — no factory needed. Every module
    uses the same dependency; the app_id is dynamic per-request.
    """
    claims = getattr(request.state, "user", None)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated identity found.",
        )

    # ── Extract org claims ───────────────────────────────────────────
    org_id = claims.get("organization_id")
    org_uuid = claims.get("organization_uuid")

    if not org_id or not org_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="JWT missing organization claims — user may not belong to an organization.",
        )

    # ── Extract app_code from x-app-code header ──────────────────────
    # security_headers = getattr(request.state, "security_headers", {})
    # app_code = security_headers.get("x-app-code", "")

    if not x_app_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing x-app-code header — frontend must send the app code.",
        )

    # ── Validate app subscription ────────────────────────────────────
    subscribed_apps = claims.get("subscribed_apps", [])
    if subscribed_apps and x_app_code not in subscribed_apps:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Organization is not subscribed to app '{x_app_code}'.",
        )

    return OrgContext(
        org_id=org_id,
        org_uuid=str(org_uuid),
        org_name=claims.get("organization_name", ""),
        user_id=claims.get("sub", "unknown"),
        user_name=claims.get("username", claims.get("sub", "unknown")),
        user_type=claims.get("userType", ""),
        app_code=x_app_code,
        app_name=x_app_code,  # Same as code for now — can resolve from DB later
        subscribed_apps=subscribed_apps,
        raw_claims=claims,
    )
