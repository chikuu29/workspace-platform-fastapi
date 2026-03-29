from typing import List, Union
from fastapi import HTTPException, status, Depends
from app.core.logger import create_logger
from app.core.security.authentications import get_authenticated_identity

logger = create_logger(__name__)


# -----------------------------
# Utility: Wildcard permission match
# -----------------------------
def permission_match(required: str, user_permissions: List[str]) -> bool:
    for perm in user_permissions:

        # Exact match
        if perm == required:
            return True

        # Wildcard match
        if perm.endswith(".*"):
            prefix = perm[:-2]
            if required.startswith(prefix):
                return True

    return False


# -----------------------------
# Base Authorization Checker
# -----------------------------
class AuthorizationChecker:
    def __init__(self, required_items: Union[str, List[str]], operator: str = "OR"):

        if isinstance(required_items, str):
            self.required_items = [required_items]
        else:
            self.required_items = required_items

        self.operator = operator.upper()


# -----------------------------
# Role Checker
# -----------------------------
class RoleChecker(AuthorizationChecker):

    async def __call__(self, identity: dict = Depends(get_authenticated_identity)):

        auth_block = identity.get("authorization") or identity
        user_roles = auth_block.get("roles", [])

        if self.operator == "AND":
            has_role = all(role in user_roles for role in self.required_items)
        else:
            has_role = any(role in user_roles for role in self.required_items)

        if not has_role:
            identity_block = identity.get("identity") or identity
            sub = identity_block.get('sub') or identity_block.get('username')
            logger.warning(
                f"Role check failed for user {sub}. "
                f"Required: {self.required_items}"
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required role(s): {', '.join(self.required_items)}"
            )

        return identity


# -----------------------------
# Permission Checker
# -----------------------------
class PermissionChecker(AuthorizationChecker):

    async def __call__(self, identity: dict = Depends(get_authenticated_identity)):
        print("PermissionChecker",identity)
        auth_block = identity.get("authorization") or identity
        print(auth_block)
        user_type = auth_block.get("user_type") or identity.get("user_type")
        is_root_user = auth_block.get("is_root_user", False) or identity.get("is_root_user", False)
        is_superuser = auth_block.get("is_superuser", False) or identity.get("is_superuser", False)
        print(user_type, is_root_user, is_superuser)
        # Bypass checks for Platform admins, Root users, and Superusers
        if user_type == "SYSTEM" or is_root_user or is_superuser:
            return identity

        user_perms = auth_block.get("permissions", [])

        if self.operator == "AND":
            has_permission = all(
                permission_match(perm, user_perms) for perm in self.required_items
            )
        else:
            has_permission = any(
                permission_match(perm, user_perms) for perm in self.required_items
            )

        if not has_permission:
            identity_block = identity.get("identity") or identity
            sub = identity_block.get('sub') or identity_block.get('username')
            logger.warning(
                f"Permission check failed for user {sub}. "
                f"Required: {self.required_items}"
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission(s): {', '.join(self.required_items)}"
            )

        return identity


# -----------------------------
# Feature Gate
# -----------------------------
class FeatureGate(AuthorizationChecker):

    async def __call__(self, identity: dict = Depends(get_authenticated_identity)):

        org_block = identity.get("organization") or identity
        user_features = org_block.get("features", []) or identity.get("features", [])

        auth_block = identity.get("authorization") or identity
        user_type = auth_block.get("user_type") or identity.get("user_type")

        # SYSTEM users bypass feature check
        if user_type == "SYSTEM":
            return identity

        if self.operator == "AND":
            has_feature = all(feat in user_features for feat in self.required_items)
        else:
            has_feature = any(feat in user_features for feat in self.required_items)

        if not has_feature:
            org_id = org_block.get("id") or identity.get("organization_id")
            logger.warning(
                f"Feature gate failed for organization {org_id}."
            )

            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Feature(s) not available in your plan: {', '.join(self.required_items)}"
            )

        return identity


# -----------------------------
# User Type Checker
# -----------------------------
class UserTypeChecker:

    def __init__(self, allowed_types: Union[str, List[str]]):

        if isinstance(allowed_types, str):
            self.allowed_types = [allowed_types.upper()]
        else:
            self.allowed_types = [t.upper() for t in allowed_types]

    async def __call__(self, identity: dict = Depends(get_authenticated_identity)):

        auth_block = identity.get("authorization") or identity
        user_type = auth_block.get("user_type") or identity.get("user_type", "ORGANIZATION")

        if user_type not in self.allowed_types:
            identity_block = identity.get("identity") or identity
            sub = identity_block.get('sub') or identity_block.get('username')
            logger.warning(
                f"User type check failed for user {sub}. "
                f"Required: {self.allowed_types}, Got: {user_type}"
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to {', '.join(self.allowed_types)} users"
            )

        return identity


# -----------------------------
# Centralized Org Identity Dependency
# Replaces duplicated _get_org_context() pattern across all routers.
# Use as: identity: dict = Depends(get_org_identity)
# -----------------------------
async def get_org_identity(
    identity: dict = Depends(get_authenticated_identity),
) -> dict:
    """
    Centralized dependency that extracts normalized organization context from
    the authenticated identity. Supports both nested and flat identity formats.

    Returns a unified dict with:
        user_type        — "SYSTEM" | "ORGANIZATION"
        is_root_user     — bool
        is_superuser     — bool
        organization_id  — int or None
        user_id          — int or None
        permissions      — list[str]
        _raw             — the original identity dict (for forwarding to services)
    """
    auth_block = identity.get("authorization") or identity
    identity_block = identity.get("identity") or identity
    org_block = identity.get("organization") or identity

    user_type = auth_block.get("user_type") or identity.get("user_type", "ORGANIZATION")
    is_root_user = auth_block.get("is_root_user", False) or identity.get("is_root_user", False)
    is_superuser = auth_block.get("is_superuser", False) or identity.get("is_superuser", False)
    permissions = auth_block.get("permissions", []) or identity.get("permissions", [])
    user_id = identity_block.get("user_id") or identity.get("user_id")
    organization_id = org_block.get("id") or identity.get("organization_id")

    return {
        "user_type": user_type,
        "is_root_user": is_root_user,
        "is_superuser": is_superuser,
        "organization_id": organization_id,
        "user_id": user_id,
        "permissions": permissions,
        "_raw": identity,  # Forward full identity when needed
    }

# Re-export for backward compatibility
__all__ = [
    "get_authenticated_identity",
    "get_org_identity",
    "permission_match",
    "RoleChecker",
    "PermissionChecker",
    "FeatureGate",
    "UserTypeChecker",
]