"""
tests/api/gym/test_checkout_api.py — API tests for Gym Membership Checkout endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import pytest


async def test_checkout_preview_success(api_client, mock_db, mock_collection):
    """Verify that checkout preview computes correct pricing and dates."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"id": "GYM-MBR-202606-0001"},
        "data": {
            "member_id": "M-1",
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "phone": "9876543210",
        },
    }
    plan_doc = {
        "_id": "507f1f77bcf86cd799439022",
        "_meta": {"id": "GYM-PLN-202606-0001"},
        "data": {
            "code": "BASIC_MONTHLY",
            "name": "Basic Monthly Plan",
            "price": 5000.0,
            "currency": "INR",
            "billing_cycle": "monthly",
            "is_active": True,
            "accent_color": "brand",
        },
    }

    records_col = MagicMock()
    records_col.find_one = AsyncMock(side_effect=[member_doc, plan_doc])
    
    tax_profiles_col = MagicMock()
    tax_profiles_col.find_one = AsyncMock(return_value=None)

    mock_db.__getitem__ = MagicMock(side_effect=lambda name: {
        "records": records_col,
        "tax_profiles": tax_profiles_col,
    }.get(name, mock_collection))

    payload = {
        "member_id": "M-1",
        "plan_code": "BASIC_MONTHLY",
        "coupon_code": "SAVE10",
    }

    response = await api_client.post(
        "/v1/gym/checkout/preview",
        json=payload,
        headers={"X-App-Code": "gym"},
    )

    if response.status_code != 200:
        print(f"RESPONSE PREVIEW JSON: {response.json()}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["member"]["name"] == "John Doe"
    assert data["data"]["plan"]["name"] == "Basic Monthly Plan"
    # price 5000, SAVE10 mock coupon -> 10% discount -> discount 500 -> taxable 4500
    # standard tax category standard higher -> 18% of 4500 -> 810 GST
    # total -> 4500 + 810 = 5310
    assert data["data"]["pricing"]["subtotal"] == 4500.0
    assert data["data"]["pricing"]["discount_amount"] == 500.0
    assert data["data"]["pricing"]["tax_amount"] == 810.0
    assert data["data"]["pricing"]["total"] == 5310.0


async def test_checkout_preview_member_not_found(api_client, mock_db):
    """Verify preview returns 404 if member is missing."""
    mock_db["records"].find_one = AsyncMock(return_value=None)

    payload = {
        "member_id": "M-INVALID",
        "plan_code": "BASIC_MONTHLY",
    }

    response = await api_client.post(
        "/v1/gym/checkout/preview",
        json=payload,
        headers={"X-App-Code": "gym"},
    )

    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert "Member 'M-INVALID' not found" in data["message"]


async def test_checkout_cash_payment_success(api_client, mock_db, mock_collection):
    """Verify immediate cash checkout creates all billing documents and activates member."""
    member_doc = {
        "_id": "507f1f77bcf86cd799439011",
        "_meta": {"id": "GYM-MBR-202606-0001"},
        "data": {
            "member_id": "M-1",
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "phone": "9876543210",
        },
    }
    plan_doc = {
        "_id": "507f1f77bcf86cd799439022",
        "_meta": {"id": "GYM-PLN-202606-0001"},
        "data": {
            "code": "BASIC_MONTHLY",
            "name": "Basic Monthly Plan",
            "price": 5000.0,
            "currency": "INR",
            "billing_cycle": "monthly",
            "is_active": True,
        },
    }

    # DB mocks:
    # 1. find_one member check
    # 2. find_one plan check
    # 3. find_one active subscription check (returns None)
    sub_doc = {
        "_id": "507f1f77bcf86cd799439033",
        "data": {
            "subscription_id": "SUB-1",
            "member_id": "M-1",
            "plan_name": "Basic Monthly Plan",
            "plan_code": "BASIC_MONTHLY",
            "status": "pending",
        }
    }
    records_col = MagicMock()
    records_col.find_one = AsyncMock(side_effect=[member_doc, plan_doc, None, sub_doc])
    records_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="sub_id"))
    records_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    records_col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
    records_col.find_one_and_update = AsyncMock(return_value={"_id": "sub_id", "data": {"status": "active"}})
    
    sequences_col = MagicMock()
    sequences_col.find_one_and_update = AsyncMock(return_value={"seq": 1, "sequence_value": 1})

    tax_profiles_col = MagicMock()
    tax_profiles_col.find_one = AsyncMock(return_value=None)

    mock_db.__getitem__ = MagicMock(side_effect=lambda name: {
        "records": records_col,
        "sequences": sequences_col,
        "tax_profiles": tax_profiles_col,
    }.get(name, mock_collection))

    payload = {
        "member_id": "M-1",
        "plan_code": "BASIC_MONTHLY",
        "payment_method": "cash",
        "notes": "Reception cash payment",
    }

    # Mock order, invoice, payment SDK processes
    mock_order = MagicMock()
    mock_order.order_number = "ORD-2026-0001"
    mock_order.subtotal = 5000.0
    mock_order.tax_amount = 900.0
    mock_order.total = 5900.0

    mock_invoice = MagicMock()
    mock_invoice.invoice_number = "INV-2026-0001"
    mock_invoice.balance_due = 5900.0

    mock_payment = MagicMock()
    mock_payment.payment_number = "PAY-2026-0001"

    with patch("app.modules.billing.services.order_service.OrderService.create", new_callable=AsyncMock) as mock_ord_create, \
         patch("app.modules.billing.services.order_service.OrderService.confirm", new_callable=AsyncMock) as mock_ord_confirm, \
         patch("app.modules.billing.services.invoice_service.InvoiceService.send", new_callable=AsyncMock) as mock_inv_send, \
         patch("app.modules.billing.services.payment_service.PaymentService.record", new_callable=AsyncMock) as mock_pay_rec:
         
        mock_ord_create.return_value = mock_order
        mock_ord_confirm.return_value = (mock_order, mock_invoice)
        mock_inv_send.return_value = mock_invoice
        mock_pay_rec.return_value = mock_payment

        response = await api_client.post(
            "/v1/gym/checkout",
            json=payload,
            headers={"X-App-Code": "gym"},
        )

        if response.status_code != 200:
            print(f"RESPONSE CHECKOUT JSON: {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "active"
        assert data["data"]["order_number"] == "ORD-2026-0001"
        assert data["data"]["invoice_number"] == "INV-2026-0001"
