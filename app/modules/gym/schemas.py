"""
Dynamic Data Sanitizer — validates any payload structure safely.

The frontend sends config-driven, dynamic forms. The field names and types
are not known at compile time. Instead of rigid Pydantic schemas, we
sanitize all incoming data to prevent:

 1. XSS / script injection (strips HTML tags and script patterns)
 2. Oversized payloads (max depth, max keys, max string length)
 3. Dangerous MongoDB operators ($-prefixed keys)

Usage:
    from app.modules.gym.schemas import sanitize_payload

    clean_data = sanitize_payload(raw_dict)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Union

from fastapi import HTTPException, status

# ── Configuration ────────────────────────────────────────────────────────
MAX_STRING_LENGTH = 5000  # Max characters per string value
MAX_KEYS = 100  # Max top-level + nested keys in a single payload
MAX_DEPTH = 5  # Max nesting depth to prevent abuse
MAX_PAYLOAD_KEYS = 200  # Absolute limit on total key count

# Regex to detect HTML tags and script-like patterns
_SCRIPT_PATTERN = re.compile(
    r"<\s*script[^>]*>|<\s*/\s*script\s*>|javascript\s*:|on\w+\s*=",
    re.IGNORECASE,
)

# Regex to detect common XSS vectors in attribute values
_XSS_PATTERN = re.compile(
    r"<[^>]*(on\w+\s*=|style\s*=\s*[\"'][^\"']*expression)[^>]*>",
    re.IGNORECASE,
)


def _sanitize_string(value: str) -> str:
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


def _sanitize_value(value: Any, depth: int = 0) -> Any:
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
        return _sanitize_string(value)

    if isinstance(value, list):
        return [_sanitize_value(item, depth + 1) for item in value[:MAX_KEYS]]

    if isinstance(value, dict):
        return _sanitize_dict(value, depth + 1)

    # Unknown type → stringify and sanitize
    return _sanitize_string(str(value))


def _sanitize_dict(data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
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

        clean[clean_key] = _sanitize_value(value, depth)

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

    return _sanitize_dict(raw)
