"""
Test 14: Dead-letter entry requires failure_class and reason.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from orchestrator.models.dead_letter import DeadLetterEntry
from orchestrator.tests.conftest import make_budget_header, make_run


def _entry(**kwargs) -> DeadLetterEntry:
    defaults = dict(
        dead_letter_id=str(uuid.uuid4()),
        task_id=None,
        run_id=None,
        failure_class="TIMEOUT",
        reason="Run exceeded max wallclock.",
        retry_count=0,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    defaults.update(kwargs)
    return DeadLetterEntry(**defaults)


class TestDeadLetterRequirements:

    def test_valid_entry_is_persisted(self, dead_letter_repo):
        entry = _entry()
        result = dead_letter_repo.create_entry(entry)
        assert result.dead_letter_id == entry.dead_letter_id

    def test_missing_failure_class_raises(self, dead_letter_repo):
        with pytest.raises(ValueError, match="failure_class"):
            dead_letter_repo.create_entry(_entry(failure_class=""))

    def test_none_failure_class_raises(self, dead_letter_repo):
        with pytest.raises((ValueError, TypeError)):
            dead_letter_repo.create_entry(_entry(failure_class=None))

    def test_missing_reason_raises(self, dead_letter_repo):
        with pytest.raises(ValueError, match="reason"):
            dead_letter_repo.create_entry(_entry(reason=""))

    def test_none_reason_raises(self, dead_letter_repo):
        with pytest.raises((ValueError, TypeError)):
            dead_letter_repo.create_entry(_entry(reason=None))

    def test_entry_linked_to_task(self, conn, task_repo, dead_letter_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        entry = _entry(task_id=task.task_id)
        dead_letter_repo.create_entry(entry)

        results = dead_letter_repo.list_for_task(task.task_id)
        assert len(results) == 1
        assert results[0].task_id == task.task_id

    def test_entry_linked_to_run(self, conn, task_repo, run_repo, dead_letter_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        run = make_run(conn, task.task_id)

        entry = _entry(task_id=task.task_id, run_id=run.run_id, failure_class="CRASH")
        dead_letter_repo.create_entry(entry)

        result = dead_letter_repo.get_entry(entry.dead_letter_id)
        assert result.run_id == run.run_id
        assert result.failure_class == "CRASH"

    def test_retry_count_stored(self, dead_letter_repo):
        entry = _entry(retry_count=3)
        dead_letter_repo.create_entry(entry)
        result = dead_letter_repo.get_entry(entry.dead_letter_id)
        assert result.retry_count == 3
