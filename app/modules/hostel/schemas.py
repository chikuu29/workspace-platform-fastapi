"""
Hostel Payload Sanitizer.

Sanitizes any custom dynamic structure sent by form fields to prevent:
1. XSS script tags
2. MongoDB operator injections
3. Tampering with system metadata keys
"""

from __future__ import annotations
import re
from typing import Any, Dict, List
from fastapi import HTTPException, status

MAX_STRING_LENGTH = 5000
MAX_KEYS = 100
MAX_DEPTH = 5
MAX_PAYLOAD_KEYS = 200

_SCRIPT_PATTERN = re.compile(
    r"<\s*script[^>]*>|<\s*/\s*script\s*>|javascript\s*:|on\w+\s*=",
    re.IGNORECASE,
)

_XSS_PATTERN = re.compile(
    r"<[^>]*(on\w+\s*=|style\s*=\s*[\"'][^\"']*expression)[^>]*>",
    re.IGNORECASE,
)


def _sanitize_string(value: str) -> str:
    value = value.strip()
    if len(value) > MAX_STRING_LENGTH:
        value = value[:MAX_STRING_LENGTH]
    value = _SCRIPT_PATTERN.sub("", value)
    value = _XSS_PATTERN.sub("", value)
    return value


def _sanitize_value(value: Any, depth: int = 0) -> Any:
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
    return _sanitize_string(str(value))


def _sanitize_dict(data: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    if len(data) > MAX_PAYLOAD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payload has too many keys (max {MAX_PAYLOAD_KEYS}).",
        )
    clean: Dict[str, Any] = {}
    for key, value in data.items():
        if key.startswith("$"):
            continue
        if key.startswith("_"):
            continue
        clean_key = str(key).strip()[:200]
        if not clean_key:
            continue
        clean[clean_key] = _sanitize_value(value, depth)
    return clean


def sanitize_payload(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object.",
        )
    return _sanitize_dict(raw)
