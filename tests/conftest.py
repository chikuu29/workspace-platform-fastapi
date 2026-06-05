"""
tests/conftest.py — Global fixtures shared across ALL test layers.

Available everywhere without any import — pytest auto-discovers this file.

Fixtures:
    mock_ctx        → real OrgContext with test org data (frozen dataclass)
    mock_db         → Motor-like MagicMock (db["collection"] → mock collection)
    mock_collection → AsyncMock collection with pre-wired async methods
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.context import OrgContext


# ── OrgContext fixture ────────────────────────────────────────────────────────

@pytest.fixture
def mock_ctx() -> OrgContext:
    """
    Real OrgContext instance with fixed test-org data.

    Using the real dataclass (not a MagicMock) ensures fixtures catch
    any future changes to OrgContext's API surface immediately.
    """
    return OrgContext(
        org_id=1001,
        org_uuid="test-org-uuid-0001",
        org_name="TestOrg",
        user_id="user-001",
        user_name="Test User",
        user_type="admin",
        app_code="testApp",
        app_name="Test Application",
        subscribed_apps=["testApp", "gym"],
        raw_claims={},
    )


# ── Database mock fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_collection() -> MagicMock:
    """
    A Motor-like collection mock with all common methods pre-wired as AsyncMocks.

    Pre-wires:
        find_one            → AsyncMock (returns None by default)
        find_one_and_update → AsyncMock (returns None by default)
        insert_one          → AsyncMock (returns mock with inserted_id)
        update_one          → AsyncMock (returns mock with modified_count=1)
        delete_one          → AsyncMock (returns mock with deleted_count=1)
        count_documents     → AsyncMock (returns 0 by default)
        find                → MagicMock cursor (chainable: .skip().limit().sort())
    """
    col = MagicMock()

    col.find_one = AsyncMock(return_value=None)
    col.find_one_and_update = AsyncMock(return_value=None)
    col.count_documents = AsyncMock(return_value=0)

    # insert_one returns an object with .inserted_id
    insert_result = MagicMock()
    insert_result.inserted_id = "mock-object-id-001"
    col.insert_one = AsyncMock(return_value=insert_result)

    # update_one returns an object with .modified_count
    update_result = MagicMock()
    update_result.modified_count = 1
    col.update_one = AsyncMock(return_value=update_result)

    # delete_one returns an object with .deleted_count
    delete_result = MagicMock()
    delete_result.deleted_count = 1
    col.delete_one = AsyncMock(return_value=delete_result)

    # Cursor: .find() returns a chainable cursor mock
    # cursor.skip(n).limit(n).sort(s).to_list(length=n) → []
    cursor = MagicMock()
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])
    col.find = MagicMock(return_value=cursor)

    return col


@pytest.fixture
def mock_db(mock_collection) -> MagicMock:
    """
    Motor-like database mock.

    db["any_collection_name"] → same mock_collection instance.
    This means all collections share the same mock — tests that need
    to distinguish collections should override mock_db[...] explicitly.
    """
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=mock_collection)
    return db
