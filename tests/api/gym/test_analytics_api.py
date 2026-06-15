"""
tests/api/gym/test_analytics_api.py — API tests for the Gym Analytics endpoints.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest


async def test_get_member_attendance_report_success(api_client, mock_db):
    """Verify that get_member_attendance_report API returns the member report correctly."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"id": "GYM-MBR-222"},
        "data": {
            "member_id": "M-222",
            "firstName": "Alice",
            "lastName": "Smith",
        },
    }
    
    attendance_record = {
        "_id": "507f1f77bcf86cd799439099",
        "_meta": {"id": "REC-1"},
        "data": {
            "timestamp": "2026-06-07T12:00:00Z",
            "date": "2026-06-07",
            "hour": 12,
            "subscription_id": "SUB-1",
            "has_active_plan": True,
            "member_id": "M-222",
            "member_name": "Alice Smith"
        }
    }

    # First find_one is for get_member
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)
    # find is for finding attendance documents
    mock_cursor = mock_db["records"].find.return_value
    mock_cursor.to_list = AsyncMock(return_value=[attendance_record])

    response = await api_client.get(
        "/v1/gym/analytics/attendance/member/GYM-MBR-222?year=2026&month=6",
        headers={"X-App-Code": "gym"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["year"] == 2026
    assert data["data"]["month"] == 6
    assert data["data"]["checked_in_days"] == [7]
    assert len(data["data"]["history"]) == 1
    assert data["data"]["history"][0]["id"] == "REC-1"
    assert data["data"]["history"][0]["date"] == "2026-06-07"
