"""
tests/unit/common/test_responses.py — Unit tests for API Response Helpers.
"""

import pytest
from fastapi import HTTPException
from app.common.responses import (
    ok,
    created,
    paginated,
    deleted,
    not_found,
    bad_request,
    conflict,
)


def test_ok_response():
    """Verify that ok returns a correct 200 OK response shape."""
    res = ok(data={"id": 123}, message="Success test")
    assert res == {
        "success": True,
        "message": "Success test",
        "data": {"id": 123},
    }

    # Verify default message
    res_default = ok()
    assert res_default["message"] == "Request completed successfully."
    assert res_default["data"] is None


def test_created_response():
    """Verify that created returns a correct 201 Created response shape."""
    res = created(data={"id": 456}, message="Created test")
    assert res == {
        "success": True,
        "message": "Created test",
        "data": {"id": 456},
    }

    # Verify default message
    res_default = created()
    assert res_default["message"] == "Resource created successfully."
    assert res_default["data"] is None


def test_paginated_response():
    """Verify that paginated returns correct pagination metadata."""
    res = paginated(data=[1, 2, 3], total=10, skip=0, limit=5, message="List retrieved")
    assert res == {
        "success": True,
        "message": "List retrieved",
        "data": [1, 2, 3],
        "pagination": {
            "total": 10,
            "skip": 0,
            "limit": 5,
            "has_more": True,
        },
    }

    # Verify has_more is False when there are no more pages
    res_no_more = paginated(data=[4, 5], total=5, skip=3, limit=2)
    assert res_no_more["pagination"]["has_more"] is False


def test_deleted_response():
    """Verify that deleted returns a correct delete response shape."""
    res = deleted(message="Item deleted")
    assert res == {
        "success": True,
        "message": "Item deleted",
    }

    res_default = deleted()
    assert res_default["message"] == "Record deleted successfully."


def test_not_found_raises_http_exception():
    """Verify not_found raises HTTPException with 404 status code and expected detail payload."""
    with pytest.raises(HTTPException) as exc_info:
        not_found(message="User not found", error_code="USER_NOT_FOUND")

    exc = exc_info.value
    assert exc.status_code == 404
    assert exc.detail == {
        "success": False,
        "message": "User not found",
        "details": {"error_code": "USER_NOT_FOUND"},
    }


def test_bad_request_raises_http_exception():
    """Verify bad_request raises HTTPException with 400 status code and expected detail payload."""
    with pytest.raises(HTTPException) as exc_info:
        bad_request(message="Invalid format", error_code="INVALID_FORMAT")

    exc = exc_info.value
    assert exc.status_code == 400
    assert exc.detail == {
        "success": False,
        "message": "Invalid format",
        "details": {"error_code": "INVALID_FORMAT"},
    }


def test_conflict_raises_http_exception():
    """Verify conflict raises HTTPException with 409 status code and detail payload."""
    with pytest.raises(HTTPException) as exc_info:
        conflict(
            message="Email already exists",
            error_code="EMAIL_CONFLICT",
            details={"email": "test@example.com"},
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.detail == {
        "success": False,
        "message": "Email already exists",
        "details": {
            "error_code": "EMAIL_CONFLICT",
            "email": "test@example.com",
        },
    }
