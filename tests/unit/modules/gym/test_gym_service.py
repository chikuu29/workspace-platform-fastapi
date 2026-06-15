import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.gym.repository import GymRepository
from app.modules.gym.service import GymService
from app.core.context import OrgContext


@pytest.fixture
def mock_ctx() -> OrgContext:
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


@pytest.fixture
def mock_repo(mock_db, mock_ctx) -> GymRepository:
    return GymRepository(mock_db, mock_ctx)


@pytest.fixture
def service(mock_repo, mock_db, mock_ctx) -> GymService:
    return GymService(mock_repo, mock_db, mock_ctx)


class TestGymRepository:
    @pytest.mark.asyncio
    async def test_get_member(self, mock_repo, mock_db):
        mock_db["records"].find_one = AsyncMock(return_value={"_id": "507f1f77bcf86cd799439011", "data": {"member_id": "M-1"}})
        res = await mock_repo.get_member("M-1")
        assert res["data"]["member_id"] == "M-1"

    @pytest.mark.asyncio
    async def test_find_duplicate_member(self, mock_repo, mock_db):
        mock_db["records"].find_one = AsyncMock(return_value={"_id": "507f1f77bcf86cd799439011", "data": {"member_id": "M-1"}})
        res = await mock_repo.find_duplicate_member("test@test.com", "12345")
        assert res is not None

    @pytest.mark.asyncio
    async def test_get_plan(self, mock_repo, mock_db):
        mock_db["records"].find_one = AsyncMock(return_value={"_id": "507f1f77bcf86cd799439011", "data": {"code": "PLAN1"}})
        res = await mock_repo.get_plan("PLAN1")
        assert res["data"]["code"] == "PLAN1"


class TestGymService:
    @pytest.mark.asyncio
    async def test_add_member_success(self, service, mock_repo, mock_db):
        # Pre-wire duplicate check (returns None)
        mock_repo.find_duplicate_member = AsyncMock(return_value=None)
        mock_repo.create_member = AsyncMock(return_value={"_meta": {"id": "GYM-MBR-1"}})

        with patch("app.modules.gym.service.SequenceService") as mock_seq_class:
            mock_seq = MagicMock()
            mock_seq.generate_id = AsyncMock(return_value="M-1")
            mock_seq_class.return_value = mock_seq

            res = await service.add_member({"email": "test@test.com"})
            assert res["member_id"] == "M-1"
            assert res["id"] == "GYM-MBR-1"

    @pytest.mark.asyncio
    async def test_create_plan_success(self, service, mock_repo):
        mock_repo.find_plan_by_code = AsyncMock(return_value=None)
        mock_repo.create_plan = AsyncMock(return_value={"data": {"code": "PLAN1"}})

        res = await service.create_plan({"name": "Pro Plan", "code": "PLAN1"})
        assert res["data"]["code"] == "PLAN1"

    @pytest.mark.asyncio
    async def test_member_checkin_success(self, service, mock_repo):
        mock_repo.get_member = AsyncMock(return_value={"data": {"firstName": "John", "lastName": "Doe"}})
        mock_repo.find_active_subscription = AsyncMock(return_value={"data": {"subscription_id": "SUB-1"}})
        mock_repo.create_attendance = AsyncMock(return_value={"data": {"member_id": "M-1"}})

        res = await service.member_checkin({"member_id": "M-1"})
        assert res["data"]["member_id"] == "M-1"

    @pytest.mark.asyncio
    async def test_get_member_attendance_report_success(self, service, mock_repo):
        mock_repo.get_member = AsyncMock(return_value={
            "_meta": {"id": "GYM-MBR-1"},
            "data": {"member_id": "M-1", "firstName": "John", "lastName": "Doe"}
        })
        mock_repo.find = AsyncMock(return_value=[
            {
                "_meta": {"id": "REC-1"},
                "data": {
                    "member_id": "M-1",
                    "date": "2026-06-15",
                    "timestamp": "2026-06-15T08:00:00Z",
                    "hour": 8,
                    "has_active_plan": True,
                    "member_name": "John Doe"
                }
            }
        ])

        res = await service.get_member_attendance_report("GYM-MBR-1", 2026, 6)
        assert res["year"] == 2026
        assert res["month"] == 6
        assert res["checked_in_days"] == [15]
        assert len(res["history"]) == 1
        assert res["history"][0]["id"] == "REC-1"

