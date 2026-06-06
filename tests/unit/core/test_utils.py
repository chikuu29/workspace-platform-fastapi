import pytest
from fastapi import HTTPException
from app.core.utils import (
    sanitize_string,
    sanitize_value,
    sanitize_dict,
    sanitize_payload,
    MAX_DEPTH,
    MAX_PAYLOAD_KEYS,
)


def test_sanitize_string_basic():
    # Whitespace strip
    assert sanitize_string("  hello world  ") == "hello world"

    # Truncation
    long_str = "a" * 6000
    assert len(sanitize_string(long_str)) == 5000


def test_sanitize_string_script_injection():
    # Simple script tags (behaves by stripping the tags themselves, leaving inner content)
    assert sanitize_string("hello <script>alert(1)</script> world") == "hello alert(1) world"
    # Case insensitivity and whitespace in script tag
    assert sanitize_string("hello <  ScRiPt >alert(1)</  sCrIpT  > world") == "hello alert(1) world"
    # Javascript URIs
    assert sanitize_string("javascript:alert(1)") == "alert(1)"
    # Event handlers
    assert sanitize_string("hello onclick=alert(1) world") == "hello alert(1) world"


def test_sanitize_string_xss_attributes():
    # Style expression and event handlers inside tags
    bad_html = '<img src="x" onerror=alert(1)>'
    assert sanitize_string(bad_html) == '<img src="x" alert(1)>'


def test_sanitize_value_primitives():
    assert sanitize_value(None) is None
    assert sanitize_value(True) is True
    assert sanitize_value(False) is False
    assert sanitize_value(42) == 42
    assert sanitize_value(3.14) == 3.14


def test_sanitize_value_nested_lists():
    raw_list = ["  text  ", 123, ["<script>alert(1)</script>", True]]
    expected = ["text", 123, ["alert(1)", True]]
    assert sanitize_value(raw_list) == expected


def test_sanitize_value_depth_limit():
    # Maximum depth is 5. Depth 6 should raise HTTPException
    deep_dict = {}
    current = deep_dict
    for _ in range(6):
        current["nested"] = {}
        current = current["nested"]

    with pytest.raises(HTTPException) as exc:
        sanitize_value(deep_dict)
    assert exc.value.status_code == 400
    assert "Payload nesting too deep" in exc.value.detail


def test_sanitize_value_unknown_type():
    class CustomType:
        def __str__(self):
            return "  custom  <script>alert(1)</script>"

    assert sanitize_value(CustomType()) == "custom  alert(1)"


def test_sanitize_dict_mongodb_operators():
    # Keys starting with $ should be dropped
    payload = {
        "valid_key": "ok",
        "$set": {"unsafe": "value"},
    }
    assert sanitize_dict(payload) == {"valid_key": "ok"}


def test_sanitize_dict_internal_keys():
    # Keys starting with _ should be dropped
    payload = {
        "valid_key": "ok",
        "_id": "12345",
        "_org": {"org_id": 1},
    }
    assert sanitize_dict(payload) == {"valid_key": "ok"}


def test_sanitize_dict_key_sanitization():
    # Key should be stripped, truncated to 200 chars
    long_key = "a" * 300
    payload = {
        "  some key  ": "value",
        long_key: "value",
    }
    clean = sanitize_dict(payload)
    assert "some key" in clean
    assert "a" * 200 in clean
    assert len(list(clean.keys())[1]) == 200


def test_sanitize_dict_max_keys():
    # Over MAX_PAYLOAD_KEYS should raise HTTPException
    payload = {f"key_{i}": i for i in range(MAX_PAYLOAD_KEYS + 1)}
    with pytest.raises(HTTPException) as exc:
        sanitize_dict(payload)
    assert exc.value.status_code == 400
    assert "Payload has too many keys" in exc.value.detail


def test_sanitize_payload_validation():
    # Must be a dict
    with pytest.raises(HTTPException) as exc:
        sanitize_payload("not a dict")
    assert exc.value.status_code == 400
    assert "Request body must be a JSON object" in exc.value.detail

    # Valid dict
    assert sanitize_payload({"key": "value"}) == {"key": "value"}
