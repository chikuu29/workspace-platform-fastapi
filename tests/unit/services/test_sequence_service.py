"""
tests/test_sequence_service.py — Unit tests for SequenceService.

Uses unittest.mock to avoid any real MongoDB connection.
All async tests run via pytest-asyncio (or the built-in asyncio runner).

Coverage:
    - _sequences property returns the correct collection
    - _next_sequence increments and returns sequence_value
    - _next_sequence upserts on first call (starts at 1)
    - generate_id produces the correct formatted string
    - generate_id zero-pads correctly at default and custom pad_length
    - generate_id uses org_name + app_code + entity as the sequence key
    - generate_id calls _next_sequence (not raw DB) — isolation test
    - Multiple sequential calls increment the counter
    - Different entities get independent counters (key isolation)
    - Bug regression: _next_sequence must call self._sequences,
      NOT self.db._sequences (attribute error guard)
    - generate_id(include_month=True) embeds YYYYMM in the ID
    - generate_id(include_month=True) uses a monthly-reset sequence key
    - generate_id(include_month=False) is unchanged — no breaking change
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── Helpers ───────────────────────────────────────────────────────────

def _make_ctx(org_name: str = "FitZone", app_code: str = "myGym") -> MagicMock:
    """Build a minimal OrgContext-like mock with the fields SequenceService reads."""
    ctx = MagicMock()
    ctx.org_name = org_name
    ctx.app_code = app_code
    return ctx


def _make_db() -> MagicMock:
    """Build a Motor-like DB mock whose collection access returns a collection mock."""
    db = MagicMock()
    collection = MagicMock()
    # db["sequences"] → collection
    db.__getitem__ = MagicMock(return_value=collection)
    return db, collection


# ── Import under test ─────────────────────────────────────────────────
from app.services.sequence_service import SequenceService


# ══════════════════════════════════════════════════════════════════════
#  _sequences property
# ══════════════════════════════════════════════════════════════════════

class TestSequencesProperty:
    def test_returns_correct_collection(self):
        """_sequences must delegate to db['sequences'] — the COLLECTION constant."""
        db, collection = _make_db()
        ctx = _make_ctx()
        svc = SequenceService(db, ctx)

        result = svc._sequences

        db.__getitem__.assert_called_once_with("sequences")
        assert result is collection


# ══════════════════════════════════════════════════════════════════════
#  _next_sequence
# ══════════════════════════════════════════════════════════════════════

class TestNextSequence:
    @pytest.mark.asyncio
    async def test_upsert_first_call_returns_one(self):
        """First call against a new sequence_name should return 1."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"_id": "FitZone:myGym:member", "sequence_value": 1}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc._next_sequence("FitZone:myGym:member")

        assert result == 1

    @pytest.mark.asyncio
    async def test_second_call_returns_incremented_value(self):
        """Second call returns 2 (simulated via side_effect)."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            side_effect=[
                {"sequence_value": 1},
                {"sequence_value": 2},
            ]
        )

        svc = SequenceService(db, ctx=_make_ctx())
        first = await svc._next_sequence("FitZone:myGym:member")
        second = await svc._next_sequence("FitZone:myGym:member")

        assert first == 1
        assert second == 2

    @pytest.mark.asyncio
    async def test_passes_correct_query_and_update(self):
        """find_one_and_update must receive the exact filter and $inc payload."""
        from pymongo import ReturnDocument

        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 5}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        await svc._next_sequence("FitZone:myGym:member")

        collection.find_one_and_update.assert_awaited_once_with(
            {"_id": "FitZone:myGym:member"},
            {"$inc": {"sequence_value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    @pytest.mark.asyncio
    async def test_returns_sequence_value_field(self):
        """Only sequence_value is returned — not the full document."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"_id": "x", "sequence_value": 42, "extra_field": "ignored"}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc._next_sequence("any")

        assert result == 42

    @pytest.mark.asyncio
    async def test_different_names_are_independent(self):
        """Each unique sequence_name has an independent counter."""
        db, collection = _make_db()
        responses = {
            "FitZone:myGym:member": {"sequence_value": 3},
            "FitZone:myGym:trainer": {"sequence_value": 1},
        }

        async def _side_effect(filter_q, *args, **kwargs):
            key = filter_q["_id"]
            return responses[key]

        collection.find_one_and_update = AsyncMock(side_effect=_side_effect)

        svc = SequenceService(db, ctx=_make_ctx())
        member_seq = await svc._next_sequence("FitZone:myGym:member")
        trainer_seq = await svc._next_sequence("FitZone:myGym:trainer")

        assert member_seq == 3
        assert trainer_seq == 1


# ══════════════════════════════════════════════════════════════════════
#  generate_id
# ══════════════════════════════════════════════════════════════════════

class TestGenerateId:
    @pytest.mark.asyncio
    async def test_default_format(self):
        """generate_id produces PREFIX-000001 with default pad_length=6."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc.generate_id(entity="member", prefix="M")

        assert result == "M-000001"

    @pytest.mark.asyncio
    async def test_zero_padding_grows_with_counter(self):
        """Zero-padding should not truncate large numbers."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1234567}  # 7 digits — exceeds pad=6
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc.generate_id(entity="member", prefix="M")

        # str.zfill never truncates — result should be "M-1234567"
        assert result == "M-1234567"

    @pytest.mark.asyncio
    async def test_custom_pad_length(self):
        """Custom pad_length=4 produces PREFIX-0001."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc.generate_id(entity="member", prefix="MBR", pad_length=4)

        assert result == "MBR-0001"

    @pytest.mark.asyncio
    async def test_sequence_key_includes_org_and_app(self):
        """sequence_name must be '{org_name}:{app_code}:{entity}' — not just entity."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1}
        )

        ctx = _make_ctx(org_name="AlphaGym", app_code="gymPro")
        svc = SequenceService(db, ctx=ctx)
        await svc.generate_id(entity="trainer", prefix="TR")

        # Inspect the filter dict passed to find_one_and_update
        call_args = collection.find_one_and_update.await_args
        filter_q = call_args[0][0]
        assert filter_q["_id"] == "AlphaGym:gymPro:trainer"

    @pytest.mark.asyncio
    async def test_different_entities_different_keys(self):
        """Member and trainer must use distinct sequence keys (org-namespaced)."""
        db, collection = _make_db()
        call_keys: list[str] = []

        async def _capture(filter_q, *args, **kwargs):
            call_keys.append(filter_q["_id"])
            return {"sequence_value": 1}

        collection.find_one_and_update = AsyncMock(side_effect=_capture)

        ctx = _make_ctx(org_name="FitZone", app_code="myGym")
        svc = SequenceService(db, ctx=ctx)

        await svc.generate_id(entity="member", prefix="M")
        await svc.generate_id(entity="trainer", prefix="TR")

        assert call_keys[0] == "FitZone:myGym:member"
        assert call_keys[1] == "FitZone:myGym:trainer"
        assert call_keys[0] != call_keys[1]

    @pytest.mark.asyncio
    async def test_different_orgs_different_keys(self):
        """Two orgs with the same entity must use different sequence keys."""
        db, collection = _make_db()
        call_keys: list[str] = []

        async def _capture(filter_q, *args, **kwargs):
            call_keys.append(filter_q["_id"])
            return {"sequence_value": 1}

        collection.find_one_and_update = AsyncMock(side_effect=_capture)

        svc_a = SequenceService(db, ctx=_make_ctx(org_name="OrgA", app_code="app"))
        svc_b = SequenceService(db, ctx=_make_ctx(org_name="OrgB", app_code="app"))

        await svc_a.generate_id(entity="member", prefix="M")
        await svc_b.generate_id(entity="member", prefix="M")

        assert call_keys[0] == "OrgA:app:member"
        assert call_keys[1] == "OrgB:app:member"

    @pytest.mark.asyncio
    async def test_sequential_calls_increment(self):
        """Three consecutive calls return M-000001, M-000002, M-000003."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            side_effect=[
                {"sequence_value": 1},
                {"sequence_value": 2},
                {"sequence_value": 3},
            ]
        )

        svc = SequenceService(db, ctx=_make_ctx())
        ids = [await svc.generate_id(entity="member", prefix="M") for _ in range(3)]

        assert ids == ["M-000001", "M-000002", "M-000003"]

    @pytest.mark.asyncio
    async def test_generate_id_calls_next_sequence_internally(self):
        """generate_id must delegate to _next_sequence — not bypass it."""
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 7}
        )

        svc = SequenceService(db, ctx=_make_ctx())

        # Spy on _next_sequence to verify delegation
        original = svc._next_sequence
        called_with: list[str] = []

        async def _spy(name: str):
            called_with.append(name)
            return await original(name)

        svc._next_sequence = _spy

        result = await svc.generate_id(entity="subscription", prefix="SUB")

        assert len(called_with) == 1
        assert called_with[0] == "FitZone:myGym:subscription"
        assert result == "SUB-000007"


# ══════════════════════════════════════════════════════════════════════
#  Bug Regression Tests
# ══════════════════════════════════════════════════════════════════════

class TestBugRegression:
    @pytest.mark.asyncio
    async def test_next_sequence_uses_property_not_raw_db_attribute(self):
        """
        Regression: line 22 of sequence_service.py incorrectly uses
        `self.db._sequences` instead of `self._sequences`.

        `self.db` does not exist (the attribute is `self._db`), so calling
        `self.db._sequences.find_one_and_update(...)` raises AttributeError.

        This test documents the bug — it WILL FAIL until the fix is applied:

            BEFORE (buggy):
                result = await self.db._sequences.find_one_and_update(...)
            AFTER (correct):
                result = await self._sequences.find_one_and_update(...)

        Once fixed, this test passes.
        """
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1}
        )

        ctx = _make_ctx()
        svc = SequenceService(db, ctx)

        # If the bug is present, this raises AttributeError: Mock has no .db
        # When fixed, it returns 1.
        try:
            result = await svc._next_sequence("FitZone:myGym:member")
            assert result == 1, (
                "Bug is fixed — _next_sequence now correctly uses self._sequences"
            )
        except AttributeError as exc:
            pytest.fail(
                f"BUG DETECTED: _next_sequence calls self.db._sequences which does not "
                f"exist. Fix: replace 'self.db._sequences' with 'self._sequences'.\n"
                f"Error: {exc}"
            )


# ══════════════════════════════════════════════════════════════════════
#  generate_id with include_month=True
# ══════════════════════════════════════════════════════════════════════

class TestGenerateIdWithMonth:
    """Tests for the include_month=True branch of generate_id."""

    @pytest.mark.asyncio
    async def test_include_month_format(self):
        """
        generate_id(include_month=True) must produce PREFIX-YYYYMM-000001.
        We freeze datetime.now so the month segment is deterministic.
        """
        from unittest.mock import patch
        from datetime import datetime, UTC, timezone

        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 1}
        )

        fixed_now = datetime(2026, 6, 5, tzinfo=UTC)

        with patch("app.services.sequence_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now

            svc = SequenceService(db, ctx=_make_ctx())
            result = await svc.generate_id(entity="member", prefix="M", include_month=True)

        assert result == "M-202606-000001"

    @pytest.mark.asyncio
    async def test_include_month_uses_monthly_sequence_key(self):
        """
        With include_month=True the sequence key must include the YYYYMM segment
        so the counter resets each month.

        Key format:  {org_name}:{app_code}:{entity}:{YYYYMM}
        """
        from unittest.mock import patch
        from datetime import datetime, UTC

        db, collection = _make_db()
        call_keys: list[str] = []

        async def _capture(filter_q, *args, **kwargs):
            call_keys.append(filter_q["_id"])
            return {"sequence_value": 1}

        collection.find_one_and_update = AsyncMock(side_effect=_capture)

        fixed_now = datetime(2026, 6, 1, tzinfo=UTC)

        with patch("app.services.sequence_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now

            svc = SequenceService(db, ctx=_make_ctx(org_name="FitZone", app_code="myGym"))
            await svc.generate_id(entity="member", prefix="M", include_month=True)

        assert call_keys[0] == "FitZone:myGym:member:202606"

    @pytest.mark.asyncio
    async def test_include_month_false_uses_continuous_key(self):
        """
        With include_month=False (default) the sequence key must NOT contain
        a month segment — counter is continuous and never resets.
        """
        db, collection = _make_db()
        call_keys: list[str] = []

        async def _capture(filter_q, *args, **kwargs):
            call_keys.append(filter_q["_id"])
            return {"sequence_value": 1}

        collection.find_one_and_update = AsyncMock(side_effect=_capture)

        svc = SequenceService(db, ctx=_make_ctx(org_name="FitZone", app_code="myGym"))
        await svc.generate_id(entity="member", prefix="M", include_month=False)

        assert call_keys[0] == "FitZone:myGym:member"
        # Must NOT contain a date segment
        assert len(call_keys[0].split(":")) == 3

    @pytest.mark.asyncio
    async def test_monthly_counter_reset_via_different_keys(self):
        """
        June and July must use separate sequence keys, so each starts at 1.
        Simulates a month boundary by patching datetime.now twice.
        """
        from unittest.mock import patch
        from datetime import datetime, UTC

        db, collection = _make_db()
        call_keys: list[str] = []

        async def _capture(filter_q, *args, **kwargs):
            call_keys.append(filter_q["_id"])
            return {"sequence_value": 1}

        collection.find_one_and_update = AsyncMock(side_effect=_capture)

        ctx = _make_ctx(org_name="FitZone", app_code="myGym")

        with patch("app.services.sequence_service.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 30, tzinfo=UTC)
            svc = SequenceService(db, ctx=ctx)
            await svc.generate_id(entity="member", prefix="M", include_month=True)

        with patch("app.services.sequence_service.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 7, 1, tzinfo=UTC)
            svc = SequenceService(db, ctx=ctx)
            await svc.generate_id(entity="member", prefix="M", include_month=True)

        # June and July must produce different sequence keys
        assert call_keys[0] == "FitZone:myGym:member:202606"
        assert call_keys[1] == "FitZone:myGym:member:202607"
        assert call_keys[0] != call_keys[1]

    @pytest.mark.asyncio
    async def test_include_month_custom_pad_length(self):
        """Custom pad_length works together with include_month=True."""
        from unittest.mock import patch
        from datetime import datetime, UTC

        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 7}
        )

        fixed_now = datetime(2026, 6, 1, tzinfo=UTC)

        with patch("app.services.sequence_service.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now

            svc = SequenceService(db, ctx=_make_ctx())
            result = await svc.generate_id(
                entity="trainer", prefix="TR", pad_length=4, include_month=True
            )

        assert result == "TR-202606-0007"

    @pytest.mark.asyncio
    async def test_default_include_month_is_false(self):
        """
        Calling generate_id without include_month must behave identically
        to include_month=False — no month segment, no breaking change.
        """
        db, collection = _make_db()
        collection.find_one_and_update = AsyncMock(
            return_value={"sequence_value": 3}
        )

        svc = SequenceService(db, ctx=_make_ctx())
        result = await svc.generate_id(entity="member", prefix="M")

        # Must NOT contain a month segment — just PREFIX-NNNNNN
        assert result == "M-000003"
        parts = result.split("-")
        assert len(parts) == 2
