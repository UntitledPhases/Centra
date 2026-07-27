"""
Tests 3-5: Promotion guard enforcement.

3. Promotion record without validator_result linkage fails.
4. Promotion with FAIL validator result fails.
5. Promotion with ESCALATE validator result fails.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from orchestrator.tests.conftest import (
    make_budget_header, make_run, make_validator_result, future_ts,
)
from orchestrator.models.promotion import PromotionRecord
from orchestrator.models.validator import ValidationStatus
from orchestrator.repositories.promotion_repository import PromotionBlockedError


def _make_record(task_id: str, validation_result_id: str) -> PromotionRecord:
    return PromotionRecord(
        promotion_record_id=str(uuid.uuid4()),
        task_id=task_id,
        source_layer="proposal",
        target_layer="durable",
        source_artifact_id=None,
        target_object_id=None,
        executor_id="executor-001",
        validator_id="validator-001",
        validation_result_id=validation_result_id,
        approval_metadata=None,
        artifact_input_hash=None,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )


class TestPromotionValidatorLinkage:
    """Test 3: promotion_record requires a validator_result to exist."""

    def test_promotion_without_existing_validator_result_fails(
        self, task_repo, promotion_repo
    ):
        header = make_budget_header()
        task = task_repo.create_task(header)

        record = _make_record(task.task_id, str(uuid.uuid4()))  # non-existent vr id
        with pytest.raises(PromotionBlockedError, match="validator_result"):
            promotion_repo.create_promotion_record(record)


class TestPromotionStatusBlocking:
    """Tests 4 and 5: FAIL and ESCALATE block promotion."""

    @pytest.mark.parametrize("status", [ValidationStatus.FAIL, ValidationStatus.ESCALATE])
    def test_blocking_status_prevents_promotion(
        self, conn, task_repo, run_repo, promotion_repo, status
    ):
        header = make_budget_header()
        task = task_repo.create_task(header)

        validator_run = make_run(conn, task.task_id, role="validator", status="completed")
        vr = make_validator_result(conn, task.task_id, validator_run.run_id, status=status)

        record = _make_record(task.task_id, vr.validator_result_id)
        with pytest.raises(PromotionBlockedError, match=status):
            promotion_repo.create_promotion_record(record)

    def test_executor_says_done_but_validator_says_fail_no_promotion(
        self, conn, task_repo, run_repo, promotion_repo
    ):
        """
        Executor run is completed (advisory self-check: 'done'),
        but validator result is FAIL → promotion still blocked.
        Deterministic failure outranks executor confidence.
        """
        header = make_budget_header()
        task = task_repo.create_task(header)

        executor_run = make_run(conn, task.task_id, role="executor", status="completed")
        run_repo.record_heartbeat(executor_run.run_id, "completed")

        validator_run = make_run(conn, task.task_id, role="validator", status="completed")
        vr = make_validator_result(
            conn, task.task_id, validator_run.run_id, status=ValidationStatus.FAIL
        )

        record = _make_record(task.task_id, vr.validator_result_id)
        with pytest.raises(PromotionBlockedError, match="FAIL"):
            promotion_repo.create_promotion_record(
                record, executor_run_id=executor_run.run_id
            )

    def test_pass_status_allows_promotion(
        self, conn, task_repo, run_repo, promotion_repo
    ):
        """PASS validator result + completed run → promotion succeeds."""
        header = make_budget_header()
        task = task_repo.create_task(header)

        executor_run = make_run(conn, task.task_id, role="executor", status="completed")
        run_repo.record_heartbeat(executor_run.run_id, "completed")

        validator_run = make_run(conn, task.task_id, role="validator", status="completed")
        vr = make_validator_result(
            conn, task.task_id, validator_run.run_id, status=ValidationStatus.PASS
        )

        record = _make_record(task.task_id, vr.validator_result_id)
        created = promotion_repo.create_promotion_record(
            record, executor_run_id=executor_run.run_id
        )
        assert created.promotion_record_id == record.promotion_record_id
