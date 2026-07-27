"""
Tests 1-2: Durable write enforcement.

1. Direct durable write without promotion_record_id fails.
2. Durable write through promoter repository with valid promotion record
   and PASS validator result succeeds.
"""
from __future__ import annotations

import uuid
import pytest

from orchestrator.tests.conftest import (
    make_budget_header, make_run, make_validator_result,
    make_promotion_record, future_ts,
)
from orchestrator.repositories.durable_repository import DurableWriteError
from orchestrator.guards.partition_guard import PartitionViolationError
from orchestrator.stores.artifact_store import ArtifactIntegrityError


class TestDirectDurableWriteBlocked:
    """Test 1: direct insert without promotion_record_id is blocked."""

    def test_approved_artifact_without_promotion_record_id_fails_at_db(self, conn):
        """
        Attempt a raw INSERT into approved_artifacts with a NULL promotion_record_id.
        The NOT NULL DB constraint must reject it.
        """
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO approved_artifacts (
                    approved_artifact_id, source_artifact_id, promotion_record_id,
                    content_hash, storage_uri, created_at
                ) VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (str(uuid.uuid4()), str(uuid.uuid4()), "abc123", "file://x", "2025-01-01T00:00:00"),
            )

    def test_validated_observation_without_promotion_record_id_fails_at_db(self, conn):
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO validated_observations (
                    validated_observation_id, source_observation_id,
                    promotion_record_id, content_hash, created_at
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (str(uuid.uuid4()), str(uuid.uuid4()), "abc123", "2025-01-01T00:00:00"),
            )

    def test_accepted_run_summary_without_promotion_record_id_fails_at_db(self, conn):
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO accepted_run_summaries (
                    run_summary_id, task_id, promotion_record_id,
                    summary_artifact_id, created_at
                ) VALUES (?, ?, NULL, ?, ?)
                """,
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), "2025-01-01T00:00:00"),
            )

    def test_durable_repo_rejects_non_promoter_role(
        self, task_repo, durable_repo
    ):
        """DurableRepository must reject any role other than 'promoter'."""
        header = make_budget_header()
        task = task_repo.create_task(header)

        with pytest.raises(PartitionViolationError, match="promoter"):
            durable_repo.promote_artifact(
                role="executor",
                approved_artifact_id=str(uuid.uuid4()),
                source_artifact_id=str(uuid.uuid4()),
                promotion_record_id=str(uuid.uuid4()),
            )

    def test_durable_repo_rejects_missing_promotion_record(
        self, task_repo, durable_repo, proposal_repo
    ):
        """DurableRepository must reject a promotion_record_id that does not exist."""
        header = make_budget_header()
        task = task_repo.create_task(header)
        artifact = proposal_repo.create_proposed_artifact(
            artifact_id=str(uuid.uuid4()),
            task_id=task.task_id,
            artifact_type="result",
            content=b"hello",
        )

        with pytest.raises(DurableWriteError, match="promotion_record"):
            durable_repo.promote_artifact(
                role="promoter",
                approved_artifact_id=str(uuid.uuid4()),
                source_artifact_id=artifact.artifact_id,
                promotion_record_id=str(uuid.uuid4()),   # does not exist
            )


class TestDurableWriteSucceeds:
    """Test 2: Durable write through promoter repo with valid promotion + PASS."""

    def test_promote_artifact_with_pass_result_succeeds(
        self, conn, task_repo, run_repo, proposal_repo, validator_repo, promotion_repo, durable_repo
    ):
        # Setup
        header = make_budget_header()
        task = task_repo.create_task(header)
        executor_run = make_run(conn, task.task_id, role="executor", status="completed")
        run_repo.record_heartbeat(executor_run.run_id, "completed")

        validator_run = make_run(conn, task.task_id, role="validator", status="completed")
        run_repo.record_heartbeat(validator_run.run_id, "completed")

        vr = make_validator_result(conn, task.task_id, validator_run.run_id, status="PASS")

        artifact = proposal_repo.create_proposed_artifact(
            artifact_id=str(uuid.uuid4()),
            task_id=task.task_id,
            artifact_type="result",
            content=b"approved content",
        )

        # Create promotion record (passes guards: PASS status, completed run)
        from orchestrator.models.promotion import PromotionRecord
        from datetime import datetime, timezone
        prec = PromotionRecord(
            promotion_record_id=str(uuid.uuid4()),
            task_id=task.task_id,
            source_layer="proposal",
            target_layer="durable",
            source_artifact_id=artifact.artifact_id,
            target_object_id=None,
            executor_id="executor-001",
            validator_id="validator-001",
            validation_result_id=vr.validator_result_id,
            approval_metadata=None,
            artifact_input_hash=artifact.content_hash,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
        )
        prec = promotion_repo.create_promotion_record(
            prec, executor_run_id=executor_run.run_id
        )

        # Promote artifact to durable layer
        approved = durable_repo.promote_artifact(
            role="promoter",
            approved_artifact_id=str(uuid.uuid4()),
            source_artifact_id=artifact.artifact_id,
            promotion_record_id=prec.promotion_record_id,
        )

        assert approved.source_artifact_id == artifact.artifact_id
        assert approved.promotion_record_id == prec.promotion_record_id
        assert approved.content_hash == artifact.content_hash
