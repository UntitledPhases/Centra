"""
Tests 12-13: Heartbeats and stale/expired run detection.

12. Heartbeat rows can be written and queried.
13. Stale or expired run is detected as non-promotable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.models.run import Run
from orchestrator.tests.conftest import (
    make_budget_header, make_run, future_ts, past_ts,
)


class TestHeartbeats:
    """Test 12: heartbeat write and query."""

    def test_record_and_retrieve_heartbeat(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id)

        hb = run_repo.record_heartbeat(run.run_id, "running", "step 1 of 3")
        assert hb.run_id == run.run_id
        assert hb.status == "running"
        assert hb.progress_note == "step 1 of 3"

    def test_multiple_heartbeats_latest_is_returned(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id)

        run_repo.record_heartbeat(run.run_id, "running", "step 1")
        run_repo.record_heartbeat(run.run_id, "running", "step 2")
        run_repo.record_heartbeat(run.run_id, "completed", "done")

        latest = run_repo.get_latest_heartbeat(run.run_id)
        assert latest.status == "completed"
        assert latest.progress_note == "done"

    def test_list_heartbeats_returns_all_in_order(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id)

        run_repo.record_heartbeat(run.run_id, "running", "a")
        run_repo.record_heartbeat(run.run_id, "running", "b")
        run_repo.record_heartbeat(run.run_id, "completed", "c")

        hbs = run_repo.list_heartbeats(run.run_id)
        assert len(hbs) == 3
        assert [h.progress_note for h in hbs] == ["a", "b", "c"]

    def test_no_heartbeat_returns_none(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id)
        assert run_repo.get_latest_heartbeat(run.run_id) is None


class TestZombieAndExpiredDetection:
    """Test 13: stale, zombie, and expired runs are non-promotable."""

    def test_completed_run_with_fresh_heartbeat_is_promotable(
        self, conn, task_repo, run_repo
    ):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id, status="completed")
        run_repo.record_heartbeat(run.run_id, "completed")

        ok, reason = run_repo.is_promotable(run.run_id, stale_threshold_seconds=300)
        assert ok is True, reason

    def test_run_with_no_heartbeat_is_not_promotable(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id, status="completed")
        # No heartbeat recorded

        ok, reason = run_repo.is_promotable(run.run_id)
        assert ok is False
        assert "no heartbeats" in reason.lower()

    def test_non_completed_run_is_not_promotable(self, conn, task_repo, run_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id, status="running")
        run_repo.record_heartbeat(run.run_id, "running")

        ok, reason = run_repo.is_promotable(run.run_id)
        assert ok is False
        assert "running" in reason

    def test_expired_run_is_not_promotable(self, conn, task_repo, run_repo):
        """Run whose expires_at is in the past is non-promotable regardless of heartbeat."""
        header = make_budget_header()
        task = task_repo.create_task(header)

        # Create an expired run directly
        expired_run = Run(
            run_id=str(uuid.uuid4()),
            task_id=task.task_id,
            work_item_id=None,
            role="executor",
            status="completed",
            started_at=datetime.now(tz=timezone.utc).isoformat(),
            expires_at=past_ts(60),   # already expired
            attempt_no=1,
            parent_run_id=None,
        )
        run_repo.create_run(expired_run)
        run_repo.record_heartbeat(expired_run.run_id, "completed")

        ok, reason = run_repo.is_promotable(expired_run.run_id)
        assert ok is False
        assert "expired" in reason.lower()

    def test_stale_heartbeat_marks_run_as_zombie(self, conn, task_repo, run_repo):
        """
        A run whose last heartbeat is older than threshold is stale (zombie).
        We simulate this by inserting an old heartbeat row directly.
        """
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id, status="completed")

        # Insert a heartbeat with a timestamp far in the past
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        conn.execute(
            """
            INSERT INTO run_heartbeats (heartbeat_id, run_id, timestamp, status, progress_note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), run.run_id, old_ts, "completed", "old"),
        )
        conn.commit()

        ok, reason = run_repo.is_promotable(run.run_id, stale_threshold_seconds=300)
        assert ok is False
        assert "stale" in reason.lower() or "zombie" in reason.lower()

    def test_nonexistent_run_is_not_promotable(self, run_repo):
        ok, reason = run_repo.is_promotable("nonexistent-run-id")
        assert ok is False
        assert "not found" in reason.lower()
