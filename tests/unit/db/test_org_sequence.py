"""
tests/unit/db/test_org_sequence.py — Unit tests for OrgSequenceService.
"""

from unittest.mock import AsyncMock, MagicMock, ANY
from datetime import datetime, timezone
import pytest
from app.db.org_sequence import OrgSequenceService, _entity_tag


def test_entity_tag_mapping():
    """Verify that entity tags are resolved correctly from mapping and fallback."""
    assert _entity_tag("member") == "MBR"
    assert _entity_tag("subscription_plan") == "PLN"
    # Fallback to first 3 chars capitalized
    assert _entity_tag("unknown_entity_type") == "UNK"
    assert _entity_tag("abc") == "ABC"


@pytest.mark.asyncio
async def test_org_sequence_monthly(mock_db, mock_ctx):
    """Verify that monthly generates sequence ID matching PREFIX-TAG-YYYYMM-0001."""
    # Pre-wire find_one_and_update to return sequential docs
    mock_collection = mock_db["sequences"]
    mock_collection.find_one_and_update = AsyncMock(
        side_effect=[
            {"_id": "some-id", "seq": 1},
            {"_id": "some-id", "seq": 2},
        ]
    )

    svc = OrgSequenceService(mock_db, mock_ctx)
    current_month = datetime.now(timezone.utc).strftime("%Y%m")

    # Generate first ID
    id_1 = await svc.monthly("member", prefix="MYGYM")
    assert id_1 == f"MYGYM-MBR-{current_month}-0001"

    # Generate second ID
    id_2 = await svc.monthly("member", prefix="MYGYM")
    assert id_2 == f"MYGYM-MBR-{current_month}-0002"

    # Verify how find_one_and_update was called
    expected_counter_id = f"{mock_ctx.org_name}:{mock_ctx.app_code}:member:{current_month}"
    mock_collection.find_one_and_update.assert_called_with(
        {"_id": expected_counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ANY
    )


@pytest.mark.asyncio
async def test_org_sequence_simple(mock_db, mock_ctx):
    """Verify that simple generates continuous ID matching PREFIX-N."""
    mock_collection = mock_db["sequences"]
    mock_collection.find_one_and_update = AsyncMock(
        side_effect=[
            {"_id": "some-id", "seq": 1},
            {"_id": "some-id", "seq": 2},
        ]
    )

    svc = OrgSequenceService(mock_db, mock_ctx)

    id_1 = await svc.simple("member", prefix="M")
    assert id_1 == "M-1"

    id_2 = await svc.simple("member", prefix="M")
    assert id_2 == "M-2"

    expected_counter_id = f"{mock_ctx.org_name}:{mock_ctx.app_code}:member:continuous"
    mock_collection.find_one_and_update.assert_called_with(
        {"_id": expected_counter_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ANY
    )
