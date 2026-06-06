from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import HTTPException, status

# ── Configuration Constants ──────────────────────────────────────────────
MAX_STRING_LENGTH = 5000  # Max characters per string value to prevent memory bloat
MAX_KEYS = 100            # Max elements per list or dictionary layer
MAX_DEPTH = 5             # Max nesting depth to prevent stack overflow/abuse
MAX_PAYLOAD_KEYS = 200    # Absolute limit on total key count in a dictionary

# Regex to detect HTML tags and script-like patterns (case-insensitive)
_SCRIPT_PATTERN = re.compile(
    r"<\s*script[^>]*>|<\s*/\s*script\s*>|javascript\s*:|on\w+\s*=",
    re.IGNORECASE,
)

# Regex to detect common XSS vectors in attribute values
_XSS_PATTERN = re.compile(
    r"<[^>]*(on\w+\s*=|style\s*=\s*[\"'][^\"']*expression)[^>]*>",
    re.IGNORECASE,
)


def get_device_type(user_agent: str) -> str:
    """Determine if the request is from a mobile or desktop based on the User-Agent."""
    mobile_keywords = ["Mobile", "Android", "iPhone", "iPad"]
    if any(keyword in user_agent for keyword in mobile_keywords):
        return "Mobile"
    return "Desktop"


def sanitize_string(value: str) -> str:
    """
    Sanitize a single string value.

    - Truncates to MAX_STRING_LENGTH
    - Strips leading/trailing whitespace
    - Removes script tags and javascript: URIs
    - Removes event handler attributes
    """
    value = value.strip()

    if len(value) > MAX_STRING_LENGTH:
        value = value[:MAX_STRING_LENGTH]

    # Remove script tags and JS URIs
    value = _SCRIPT_PATTERN.sub("", value)
    value = _XSS_PATTERN.sub("", value)

    return value


def sanitize_value(value: Any, depth: int = 0) -> Any:
    """
    Recursively sanitize a value at a given nesting depth.

    Handles: str, int, float, bool, None, list, dict.
    Rejects unknown types by converting to string.
    """
    if depth > MAX_DEPTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payload nesting too deep (max {MAX_DEPTH} levels).",
        )

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        return sanitize_string(value)

    if isinstance(value, list):
        return [sanitize_value(item, depth + 1) for item in value[:MAX_KEYS]]

    if isinstance(value, dict):
        return sanitize_dict(value, depth + 1)

    # Unknown type → stringify and sanitize
    return sanitize_string(str(value))


def sanitize_dict(data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    """
    Sanitize a dict:
    - Reject keys starting with $ (MongoDB operator injection)
    - Reject keys starting with _ (reserved for _org, _meta)
    - Sanitize all values recursively
    """
    if len(data) > MAX_PAYLOAD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payload has too many keys (max {MAX_PAYLOAD_KEYS}).",
        )

    clean: Dict[str, Any] = {}

    for key, value in data.items():
        # Block MongoDB operator injection — $set, $inc, $where, etc.
        if key.startswith("$"):
            continue  # Silently drop — don't reveal to attacker

        # Block reserved prefixes — _org, _meta, _id are system fields
        if key.startswith("_"):
            continue

        # Sanitize the key itself (strip whitespace, limit length)
        clean_key = str(key).strip()[:200]

        if not clean_key:
            continue

        clean[clean_key] = sanitize_value(value, depth)

    return clean


def sanitize_payload(raw: Any) -> Dict[str, Any]:
    """
    Top-level sanitizer for incoming request payloads.

    Accepts any dict structure from the dynamic frontend forms.
    Returns a clean dict safe for MongoDB insertion.

    Raises:
        HTTPException 400 if payload is not a dict, too deep, or too large.
    """
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object.",
        )

    return sanitize_dict(raw)
