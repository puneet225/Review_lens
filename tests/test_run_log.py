"""Tests for SQLite run log and idempotency checker."""

from __future__ import annotations

from datetime import datetime

import pytest

from review_pulse.agent.idempotency import check_run_exists
from review_pulse.store.models import RunRecord
from review_pulse.store.run_log import RunLog


@pytest.fixture
async def run_log(tmp_path) -> RunLog:
    rl = RunLog(tmp_path / "test.db")
    await rl.init_db()
    yield rl
    await rl.close()


# ---------------------------------------------------------------------------
# E1.4 — RunLog CRUD
# ---------------------------------------------------------------------------


class TestRunLog:
    @pytest.mark.asyncio
    async def test_init_db_idempotent(self, tmp_path) -> None:
        rl = RunLog(tmp_path / "test.db")
        await rl.init_db()
        await rl.init_db()  # Second call should not error
        await rl.close()

    @pytest.mark.asyncio
    async def test_insert_and_get(self, run_log: RunLog) -> None:
        record = RunRecord(product="groww", iso_week="2026-W18")
        await run_log.insert_run(record)
        fetched = await run_log.get_run("groww", "2026-W18")
        assert fetched is not None
        assert fetched.product == "groww"
        assert fetched.iso_week == "2026-W18"
        assert fetched.id == record.id

    @pytest.mark.asyncio
    async def test_duplicate_insert_raises(self, run_log: RunLog) -> None:
        r1 = RunRecord(product="groww", iso_week="2026-W18")
        await run_log.insert_run(r1)
        r2 = RunRecord(product="groww", iso_week="2026-W18")
        with pytest.raises(Exception):  # IntegrityError
            await run_log.insert_run(r2)

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, run_log: RunLog) -> None:
        result = await run_log.get_run("nonexistent", "2026-W01")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_run_status(self, run_log: RunLog) -> None:
        record = RunRecord(product="groww", iso_week="2026-W18")
        await run_log.insert_run(record)
        now = datetime.utcnow()
        await run_log.update_run(record.id, status="success", completed_at=now)
        fetched = await run_log.get_run("groww", "2026-W18")
        assert fetched is not None
        assert fetched.status == "success"
        assert fetched.completed_at is not None

    @pytest.mark.asyncio
    async def test_list_runs(self, run_log: RunLog) -> None:
        for i in range(5):
            r = RunRecord(product="groww", iso_week=f"2026-W{i+1:02d}")
            await run_log.insert_run(r)
        records = await run_log.list_runs(limit=3)
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_list_runs_filter_by_product(self, run_log: RunLog) -> None:
        await run_log.insert_run(RunRecord(product="groww", iso_week="2026-W18"))
        await run_log.insert_run(RunRecord(product="indmoney", iso_week="2026-W18"))
        records = await run_log.list_runs(product="groww")
        assert len(records) == 1
        assert records[0].product == "groww"

    @pytest.mark.asyncio
    async def test_list_runs_empty_db(self, run_log: RunLog) -> None:
        records = await run_log.list_runs()
        assert records == []


# ---------------------------------------------------------------------------
# E1.5 — Idempotency Checker
# ---------------------------------------------------------------------------


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_no_prior_run(self, run_log: RunLog) -> None:
        result = await check_run_exists(run_log, "groww", "2026-W18")
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_run_blocks(self, run_log: RunLog) -> None:
        record = RunRecord(product="groww", iso_week="2026-W18", status="success")
        await run_log.insert_run(record)
        result = await check_run_exists(run_log, "groww", "2026-W18")
        assert result is True

    @pytest.mark.asyncio
    async def test_failed_run_does_not_block(self, run_log: RunLog) -> None:
        record = RunRecord(product="groww", iso_week="2026-W18", status="failed")
        await run_log.insert_run(record)
        result = await check_run_exists(run_log, "groww", "2026-W18")
        assert result is False

    @pytest.mark.asyncio
    async def test_interrupted_run_does_not_block(self, run_log: RunLog) -> None:
        record = RunRecord(product="groww", iso_week="2026-W18", status="interrupted")
        await run_log.insert_run(record)
        result = await check_run_exists(run_log, "groww", "2026-W18")
        assert result is False
