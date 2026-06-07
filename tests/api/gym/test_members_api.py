"""
tests/api/gym/test_members_api.py — API tests for the Gym Members CRUD endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import pytest


async def test_add_member_success(api_client, mock_db):
    """Verify posting a new member creates it and returns 201."""
    # Pre-wire duplicate check (returns None)
    mock_db["records"].find_one = AsyncMock(return_value=None)
    
    # Pre-wire simple ID sequence
    mock_db["sequences"].find_one_and_update = AsyncMock(return_value={"seq": 10, "sequence_value": 10})

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


async def test_get_member_membership_success(api_client, mock_db):
    """Verify get_member_membership returns the active membership and plan details."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1", "firstName": "Alice"},
    }
    active_sub = {
        "_id": "507f1f77bcf86cd799439022",
        "_meta": {"record_id": "GYM-SUB-202606-0001"},
        "data": {
            "subscription_id": "SUB-1",
            "member_id": "M-1",
            "plan_code": "PRO",
            "status": "active",
        }
    }
    plan_doc = {
        "_id": "507f1f77bcf86cd799439033",
        "_meta": {"record_id": "GYM-PLN-202606-0001"},
        "data": {"code": "PRO", "name": "Pro Plan"}
    }

    mock_db["records"].find_one = AsyncMock(side_effect=[member_doc, active_sub, plan_doc])

    response = await api_client.get(
        "/v1/gym/members/M-1/membership",
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["data"]["subscription_id"] == "SUB-1"
    assert data["data"]["plan_details"]["name"] == "Pro Plan"


async def test_get_member_orders_success(api_client, mock_db):
    """Verify get_member_orders returns the paginated orders list."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    }
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)

    mock_order = MagicMock()
    mock_order.order_number = "ORD-1"
    mock_order.status = "pending"
    mock_order.subtotal = 100.0
    mock_order.tax_amount = 18.0
    mock_order.total = 118.0
    mock_order.currency = "INR"
    mock_order.invoice_ref = ""
    mock_order.notes = "Order notes"
    mock_order.meta_info.created.at = datetime(2026, 6, 7, tzinfo=timezone.utc)

    with patch("app.modules.billing.documents.order_doc.OrderDoc.org_find", new_callable=AsyncMock) as mock_find, \
         patch("app.modules.billing.documents.order_doc.OrderDoc.org_count", new_callable=AsyncMock) as mock_count:
        mock_find.return_value = [mock_order]
        mock_count.return_value = 1

        response = await api_client.get(
            "/v1/gym/members/M-1/orders?page=1&limit=10",
            headers={"X-App-Code": "gym"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["order_number"] == "ORD-1"
        assert data["pagination"]["total"] == 1


async def test_get_member_invoices_success(api_client, mock_db):
    """Verify get_member_invoices returns the paginated invoices list."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    }
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)

    mock_invoice = MagicMock()
    mock_invoice.invoice_number = "INV-1"
    mock_invoice.status = "sent"
    mock_invoice.subtotal = 100.0
    mock_invoice.tax_breakdown.total_tax = 18.0
    mock_invoice.total = 118.0
    mock_invoice.amount_paid = 0.0
    mock_invoice.balance_due = 118.0
    mock_invoice.currency = "INR"
    mock_invoice.issue_date = "2026-06-07"
    mock_invoice.due_date = "2026-07-07"
    mock_invoice.meta_info.created.at = datetime(2026, 6, 7, tzinfo=timezone.utc)

    with patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_find", new_callable=AsyncMock) as mock_find, \
         patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_count", new_callable=AsyncMock) as mock_count:
        mock_find.return_value = [mock_invoice]
        mock_count.return_value = 1

        response = await api_client.get(
            "/v1/gym/members/M-1/invoices?page=1&limit=10",
            headers={"X-App-Code": "gym"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["invoice_number"] == "INV-1"


async def test_get_member_payments_success(api_client, mock_db):
    """Verify get_member_payments returns the paginated payments list."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    }
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)

    mock_invoice = MagicMock()
    mock_invoice.invoice_number = "INV-1"

    mock_payment = MagicMock()
    mock_payment.payment_number = "PAY-1"
    mock_payment.invoice_ref = "INV-1"
    mock_payment.amount = 118.0
    mock_payment.currency = "INR"
    mock_payment.method = "cash"
    mock_payment.status = "captured"
    mock_payment.payment_date = "2026-06-07"
    mock_payment.transaction_ref = "TXN-1"
    mock_payment.notes = "Payment notes"
    mock_payment.meta_info.created.at = datetime(2026, 6, 7, tzinfo=timezone.utc)

    with patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_find", new_callable=AsyncMock) as mock_inv_find, \
         patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_count", new_callable=AsyncMock) as mock_inv_count, \
         patch("app.modules.billing.documents.payment_doc.PaymentDoc.org_find", new_callable=AsyncMock) as mock_pay_find, \
         patch("app.modules.billing.documents.payment_doc.PaymentDoc.org_count", new_callable=AsyncMock) as mock_pay_count:
        mock_inv_find.return_value = [mock_invoice]
        mock_inv_count.return_value = 1
        mock_pay_find.return_value = [mock_payment]
        mock_pay_count.return_value = 1

        response = await api_client.get(
            "/v1/gym/members/M-1/payments?page=1&limit=10",
            headers={"X-App-Code": "gym"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        assert data["data"][0]["payment_number"] == "PAY-1"


async def test_get_member_attendance_success(api_client, mock_db):
    """Verify get_member_attendance returns the paginated check-ins list."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    }
    attendance_record = {
        "_id": "507f1f77bcf86cd799439099",
        "_meta": {"created": {"at": "2026-06-07T12:00:00Z"}},
        "data": {
            "timestamp": "2026-06-07T12:00:00Z",
            "date": "2026-06-07",
            "hour": 12,
            "subscription_id": "SUB-1",
            "has_active_plan": True
        }
    }

    # We call find_one for member, then find for attendance records, then count for attendance records
    mock_db["records"].find_one = AsyncMock(return_value=member_doc)
    mock_cursor = mock_db["records"].find.return_value
    mock_cursor.to_list = AsyncMock(return_value=[attendance_record])
    mock_db["records"].count_documents = AsyncMock(return_value=1)

    response = await api_client.get(
        "/v1/gym/members/M-1/attendance?page=1&limit=10",
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["subscription_id"] == "SUB-1"


async def test_get_member_timeline_success(api_client, mock_db):
    """Verify get_member_timeline aggregates all activities."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"record_id": "GYM-MBR-202606-0001"},
        "data": {"member_id": "M-1"},
    }
    attendance_record = {
        "_id": "507f1f77bcf86cd799439099",
        "_meta": {"created": {"at": "2026-06-07T12:00:00Z"}},
        "data": {
            "timestamp": "2026-06-07T12:00:00Z",
            "date": "2026-06-07",
            "hour": 12,
            "subscription_id": "SUB-1",
            "has_active_plan": True
        }
    }
    subscription_record = {
        "_id": "507f1f77bcf86cd799439022",
        "_meta": {"created": {"at": "2026-06-07T10:00:00Z"}},
        "data": {
            "subscription_id": "SUB-1",
            "plan_name": "Premium",
            "billing_cycle": "monthly",
            "status": "active"
        }
    }

    mock_db["records"].find_one = AsyncMock(return_value=member_doc)

    # We call find for attendance records and subscription records
    mock_cursor = mock_db["records"].find.return_value
    mock_cursor.to_list = AsyncMock(side_effect=[[attendance_record], [subscription_record]])

    with patch("app.modules.billing.documents.order_doc.OrderDoc.org_find", new_callable=AsyncMock) as mock_ord_find, \
         patch("app.modules.billing.documents.order_doc.OrderDoc.org_count", new_callable=AsyncMock) as mock_ord_count, \
         patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_find", new_callable=AsyncMock) as mock_inv_find, \
         patch("app.modules.billing.documents.invoice_doc.InvoiceDoc.org_count", new_callable=AsyncMock) as mock_inv_count, \
         patch("app.modules.billing.documents.payment_doc.PaymentDoc.org_find", new_callable=AsyncMock) as mock_pay_find, \
         patch("app.modules.billing.documents.payment_doc.PaymentDoc.org_count", new_callable=AsyncMock) as mock_pay_count:
        mock_ord_find.return_value = []
        mock_ord_count.return_value = 0
        mock_inv_find.return_value = []
        mock_inv_count.return_value = 0
        mock_pay_find.return_value = []
        mock_pay_count.return_value = 0

        response = await api_client.get(
            "/v1/gym/members/M-1/timeline?page=1&limit=10",
            headers={"X-App-Code": "gym"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 2
        # Check sorting (checkin is at 12:00, subscription is at 10:00)
        assert data["data"][0]["type"] == "checkin"
        assert data["data"][1]["type"] == "subscription"

