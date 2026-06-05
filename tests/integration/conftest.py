"""
tests/integration/conftest.py — Integration test layer fixtures.
"""

import pytest
from app.common.org_repository import OrgRepository


@pytest.fixture
def org_repo(mock_db, mock_ctx) -> OrgRepository:
    """An instance of OrgRepository pre-wired with mock_db and mock_ctx."""
    return OrgRepository(mock_db, "records", mock_ctx)
