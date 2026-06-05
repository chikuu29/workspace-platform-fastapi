"""
tests/integration/db/test_org_repository.py — Integration tests for OrgRepository.
"""

from unittest.mock import AsyncMock, MagicMock, ANY
import pytest
from app.common.org_repository import OrgRepository


@pytest.mark.asyncio
async def test_org_repository_find(org_repo, mock_db, mock_ctx):
    """Verify find() merges org filter and delegates skip/limit/sort correctly."""
    mock_collection = mock_db["records"]
    
    # Pre-wire find to return chainable cursor and test documents
    mock_cursor = mock_collection.find.return_value
    mock_cursor.to_list.return_value = [
        {"_id": "507f1f77bcf86cd799439011", "data": {"name": "Alice"}},
        {"_id": "507f1f77bcf86cd799439012", "data": {"name": "Bob"}},
    ]

    # Run find query
    results = await org_repo.find(
        query={"data.role": "member"},
        sort=[("data.name", 1)],
        skip=10,
        limit=20,
    )

    # Check query compilation
    mock_collection.find.assert_called_once_with({
        "_org.org_id": mock_ctx.org_id,
        "_meta.is_deleted": False,
        "data.role": "member",
    })
    
    mock_cursor.skip.assert_called_once_with(10)
    mock_cursor.limit.assert_called_once_with(20)
    mock_cursor.sort.assert_called_once_with([("data.name", 1)])
    mock_cursor.to_list.assert_called_once_with(length=20)

    # Verify ID stringification
    assert results[0]["_id"] == "507f1f77bcf86cd799439011"
    assert results[1]["_id"] == "507f1f77bcf86cd799439012"


@pytest.mark.asyncio
async def test_org_repository_find_include_deleted(org_repo, mock_db, mock_ctx):
    """Verify find(include_deleted=True) removes the is_deleted constraint."""
    mock_collection = mock_db["records"]
    await org_repo.find(include_deleted=True)

    # Check query does not contain _meta.is_deleted
    mock_collection.find.assert_called_once_with({
        "_org.org_id": mock_ctx.org_id,
    })


@pytest.mark.asyncio
async def test_org_repository_find_one(org_repo, mock_db, mock_ctx):
    """Verify find_one() filters by active org scopes."""
    mock_collection = mock_db["records"]
    mock_collection.find_one.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "data": {"name": "Charlie"},
    }

    result = await org_repo.find_one({"data.email": "charlie@test.com"})

    mock_collection.find_one.assert_called_once_with({
        "_org.org_id": mock_ctx.org_id,
        "_meta.is_deleted": False,
        "data.email": "charlie@test.com",
    })
    assert result["_id"] == "507f1f77bcf86cd799439011"


@pytest.mark.asyncio
async def test_org_repository_count(org_repo, mock_db, mock_ctx):
    """Verify count() correctly delegates count_documents."""
    mock_collection = mock_db["records"]
    mock_collection.count_documents.return_value = 42

    cnt = await org_repo.count({"data.status": "active"})

    mock_collection.count_documents.assert_called_once_with({
        "_org.org_id": mock_ctx.org_id,
        "_meta.is_deleted": False,
        "data.status": "active",
    })
    assert cnt == 42


@pytest.mark.asyncio
async def test_org_repository_insert_one(org_repo, mock_db, mock_ctx):
    """Verify insert_one stamps org and meta blocks, fetching sequence ID."""
    mock_records_col = mock_db["records"]
    mock_seq_col = mock_db["sequences"]

    # Pre-wire sequence query
    mock_seq_col.find_one_and_update.return_value = {
        "_id": "seq-id",
        "seq": 15,
    }

    # Pre-wire insert_one response
    mock_insert_result = MagicMock()
    mock_insert_result.inserted_id = "507f1f77bcf86cd799439011"
    mock_records_col.insert_one.return_value = mock_insert_result

    input_data = {"name": "David", "age": 30}
    result = await org_repo.insert_one(input_data, entity_type="member", prefix="GYM")

    # Assert correct structure is saved
    mock_records_col.insert_one.assert_called_once_with({
        "_org": {
            "org_id": mock_ctx.org_id,
            "org_uuid": mock_ctx.org_uuid,
            "org_name": mock_ctx.org_name,
            "app_code": mock_ctx.app_code,
            "app_name": mock_ctx.app_name,
        },
        "_meta": {
            "entity_type": "member",
            "record_id": ANY,
            "version": 1,
            "is_deleted": False,
            "created": {"at": ANY, "by": mock_ctx.user_id},
            "updated": {"at": ANY, "by": mock_ctx.user_id},
            "deleted": None,
        },
        "data": input_data,
        "_id": "507f1f77bcf86cd799439011",
    })

    assert result["_id"] == "507f1f77bcf86cd799439011"
    assert "record_id" in result["_meta"]
    assert result["_meta"]["record_id"].startswith("GYM-MBR-")


@pytest.mark.asyncio
async def test_org_repository_update_one(org_repo, mock_db, mock_ctx):
    """Verify update_one maps update fields to 'data.*' and stamps update details."""
    mock_collection = mock_db["records"]
    mock_collection.find_one_and_update.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "data": {"status": "inactive"},
    }

    result = await org_repo.update_one(
        {"_meta.record_id": "GYM-MBR-202605-0015"},
        {"status": "inactive"},
    )

    mock_collection.find_one_and_update.assert_called_once_with(
        {
            "_org.org_id": mock_ctx.org_id,
            "_meta.is_deleted": False,
            "_meta.record_id": "GYM-MBR-202605-0015",
        },
        {
            "$set": {
                "data.status": "inactive",
                "_meta.updated.at": ANY,
                "_meta.updated.by": mock_ctx.user_id,
            },
            "$inc": {"_meta.version": 1},
        },
        return_document=ANY,
    )
    assert result is not None


@pytest.mark.asyncio
async def test_org_repository_soft_delete(org_repo, mock_db, mock_ctx):
    """Verify soft_delete stamps delete meta and returns True if successful."""
    mock_collection = mock_db["records"]
    mock_update_result = MagicMock()
    mock_update_result.modified_count = 1
    mock_collection.update_one.return_value = mock_update_result

    success = await org_repo.soft_delete({"_meta.record_id": "GYM-MBR-001"})

    mock_collection.update_one.assert_called_once_with(
        {
            "_org.org_id": mock_ctx.org_id,
            "_meta.is_deleted": False,
            "_meta.record_id": "GYM-MBR-001",
        },
        {
            "$set": {
                "_meta.is_deleted": True,
                "_meta.deleted": {"at": ANY, "by": mock_ctx.user_id},
                "_meta.updated.at": ANY,
                "_meta.updated.by": mock_ctx.user_id,
            },
            "$inc": {"_meta.version": 1},
        },
    )
    assert success is True


@pytest.mark.asyncio
async def test_org_repository_hard_delete(org_repo, mock_db, mock_ctx):
    """Verify hard_delete triggers a physical delete with org filter."""
    mock_collection = mock_db["records"]
    mock_delete_result = MagicMock()
    mock_delete_result.deleted_count = 1
    mock_collection.delete_one.return_value = mock_delete_result

    success = await org_repo.hard_delete({"_meta.record_id": "GYM-MBR-001"})

    mock_collection.delete_one.assert_called_once_with({
        "_org.org_id": mock_ctx.org_id,
        "_meta.record_id": "GYM-MBR-001",
    })
    assert success is True
