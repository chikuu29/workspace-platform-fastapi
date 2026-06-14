"""
tests/api/gym/test_qr_endpoints.py — API tests for QR Code and membership pass endpoints.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest


async def test_get_member_qr_success(api_client, mock_db):
    """Verify that get_member_qr generates and streams PNG QR code."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"id": "GYM-MBR-222"},
        "data": {
            "member_id": "M-222",
            "firstName": "Alice",
            "lastName": "Smith",
        },
    }
    
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)
    
    response = await api_client.get(
        "/v1/gym/members/M-222/qr",
        headers={"X-App-Code": "gym"},
    )
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert len(response.content) > 0


async def test_email_membership_card_success(api_client, mock_db):
    """Verify simulated emailing of membership card."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"id": "GYM-MBR-222", "created": {"at": "2026-06-14T12:00:00Z"}},
        "data": {
            "member_id": "M-222",
            "firstName": "Alice",
            "lastName": "Smith",
            "email": "alice@example.com",
            "status": "active",
        },
    }
    
    # Mock finding member and finding active subscription (returning None)
    mock_db["records"].find_one = AsyncMock(side_effect=[member_doc, None])
    
    response = await api_client.post(
        "/v1/gym/members/M-222/email-card",
        headers={"X-App-Code": "gym"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Membership card emailed successfully" in data["message"]
