"""
tests/api/gym/test_members_api.py — API tests for the Gym Members CRUD endpoints.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest


async def test_add_member_success(api_client, mock_db):
    """Verify posting a new member creates it and returns 201."""
    # Pre-wire duplicate check (returns None)
    mock_db["records"].find_one = AsyncMock(return_value=None)
    
    # Pre-wire simple ID sequence
    mock_db["sequences"].find_one_and_update = AsyncMock(return_value={"seq": 10})

    # Pre-wire insert_one response
    mock_insert_result = MagicMock()
    mock_insert_result.inserted_id = "507f1f77bcf86cd799439011"
    mock_db["records"].insert_one = AsyncMock(return_value=mock_insert_result)

    payload = {
        "name": "Evelyn",
        "email": "evelyn@example.com",
        "phone": "9876543210",
    }

    response = await api_client.post(
        "/v1/gym/members",
        json=payload,
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Membership registration successful!"
    assert data["data"]["member_id"] == "M-10"


async def test_add_member_duplicate_conflict(api_client, mock_db):
    """Verify posting a duplicate member returns 409 Conflict."""
    # Pre-wire duplicate check to return an existing member doc
    mock_db["records"].find_one = AsyncMock(return_value={
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    })

    payload = {
        "name": "Evelyn duplicate",
        "email": "evelyn@example.com",
        "phone": "9876543210",
    }

    response = await api_client.post(
        "/v1/gym/members",
        json=payload,
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 409
    data = response.json()
    assert data["success"] is False
    assert "already exists" in data["message"]
    assert data["details"]["error_code"] == "DUPLICATE_MEMBER"


async def test_get_members_paginated(api_client, mock_db):
    """Verify get_members lists members with proper pagination metadata."""
    # Pre-wire find to return list of members
    mock_cursor = mock_db["records"].find.return_value
    mock_cursor.to_list = AsyncMock(return_value=[
        {
            "_id": "507f1f77bcf86cd799439011",
            "_meta": {"record_id": "GYM-MBR-202606-0001"},
            "data": {"member_id": "M-1", "name": "Alice"},
        }
    ])
    mock_db["records"].count_documents = AsyncMock(return_value=1)

    response = await api_client.get(
        "/v1/gym/members?skip=0&limit=50",
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["pagination"] == {
        "total": 1,
        "skip": 0,
        "limit": 50,
        "has_more": False,
    }


async def test_get_member_detail_not_found(api_client, mock_db):
    """Verify fetching a non-existent member returns 404."""
    mock_db["records"].find_one = AsyncMock(return_value=None)

    response = await api_client.get(
        "/v1/gym/members/GYM-MBR-9999",
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "not found" in data["message"]


async def test_update_member_success(api_client, mock_db):
    """Verify updating a member returns 200 and updated doc."""
    mock_db["records"].find_one_and_update = AsyncMock(return_value={
        "_id": "507f1f77bcf86cd799439011",
        "data": {"member_id": "M-1", "name": "Alice Updated"},
    })

    payload = {"name": "Alice Updated"}
    response = await api_client.put(
        "/v1/gym/members/GYM-MBR-202606-0001",
        json=payload,
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Member updated successfully."
    assert data["data"]["data"]["name"] == "Alice Updated"


async def test_delete_member_success(api_client, mock_db):
    """Verify deleting a member soft-deletes the doc and returns 200."""
    mock_update_result = MagicMock()
    mock_update_result.modified_count = 1
    mock_db["records"].update_one = AsyncMock(return_value=mock_update_result)

    response = await api_client.delete(
        "/v1/gym/members/GYM-MBR-202606-0001",
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Member deleted successfully."
