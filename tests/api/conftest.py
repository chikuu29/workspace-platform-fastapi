"""
tests/api/conftest.py — API test layer fixtures.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_db as get_database
from app.core.context import get_org_context
from app.core.security.authentications import get_authenticated_identity


@pytest.fixture
async def api_client(mock_db, mock_ctx):
    """
    An HTTP client for hitting API endpoints with database, auth, and context bypassed/mocked.
    """
    # Apply dependency overrides
    app.dependency_overrides[get_database] = lambda: mock_db
    app.dependency_overrides[get_org_context] = lambda: mock_ctx
    app.dependency_overrides[get_authenticated_identity] = lambda: {
        "organization_id": mock_ctx.org_id,
        "organization_uuid": mock_ctx.org_uuid,
        "organization_name": mock_ctx.org_name,
        "sub": mock_ctx.user_id,
        "username": mock_ctx.user_name,
        "userType": mock_ctx.user_type,
        "subscribed_apps": mock_ctx.subscribed_apps,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    # Clear overrides
    app.dependency_overrides.clear()
