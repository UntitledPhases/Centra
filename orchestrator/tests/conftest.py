"""
Shared fixtures for orchestration kernel tests.

Uses in-memory SQLite for isolation.
"""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.db.connection import bootstrap
from orchestrator.stores.artifact_store import ArtifactStore
from orchestrator.repositories.protected_config import ProtectedConfigRepository
from orchestrator.repositories.task_repository import TaskRepository
from orchestrator.repositories.run_repository import RunRepository
from orchestrator.repositories.proposal_repository import ProposalRepository
from orchestrator.repositories.validator_repository import ValidatorRepository
from orchestrator.repositories.promotion_repository import PromotionRepository
from orchestrator.repositories.durable_repository import DurableRepository
from orchestrator.repositories.dead_letter_repository import DeadLetterRepository
from orchestrator.models.budget import BudgetHeader, RootBudgetEnvelope
from orchestrator.models.run import Run
from orchestrator.models.validator import ValidatorResult, ValidationStatus
from orchestrator.models.promotion import PromotionRecord


# ------------------------------------------------------------------
# DB + store fixtures
# ------------------------------------------------------------------

@pytest.fixture
def conn():
    """In-memory SQLite connection with schema applied."""
    c = bootstrap(":memory:")
    yield c
    c.close()


@pytest.fixture
def artifact_dir(tmp_path):
    return tmp_path / "artifacts"


@pytest.fixture
def artifact_store(artifact_dir):
    return ArtifactStore(artifact_dir)


# ------------------------------------------------------------------
# Repository fixtures
# ------------------------------------------------------------------

@pytest.fixture
def protected_repo(conn):
    return ProtectedConfigRepository(conn)


@pytest.fixture
def task_repo(conn):
    return TaskRepository(conn)


@pytest.fixture
def run_repo(conn):
    return RunRepository(conn)


@pytest.fixture
def proposal_repo(conn, artifact_store):
    return ProposalRepository(conn, artifact_store)


@pytest.fixture
def validator_repo(conn):
    return ValidatorRepository(conn)


@pytest.fixture
def promotion_repo(conn, validator_repo, run_repo):
    return PromotionRepository(conn, validator_repo, run_repo)


@pytest.fixture
def durable_repo(conn, promotion_repo, proposal_repo, artifact_store):
    return DurableRepository(conn, promotion_repo, proposal_repo, artifact_store)


@pytest.fixture
def dead_letter_repo(conn):
    return DeadLetterRepository(conn)


# ------------------------------------------------------------------
# Helper factories
# ------------------------------------------------------------------

def future_ts(seconds: int = 3600) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)).isoformat()


def past_ts(seconds: int = 60) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)).isoformat()


def make_budget_header(
    task_id: str = None,
    parent_task_id: str = None,
    expires_at: str = None,
    max_tokens: int = 10000,
    max_subagents: int = 4,
    max_depth: int = 3,
    max_retries: int = 2,
    promotion_target: str = "durable",
) -> BudgetHeader:
    return BudgetHeader(
        task_id=task_id or str(uuid.uuid4()),
        parent_task_id=parent_task_id,
        task_type="unit_task",
        criticality_level="high",
        max_depth=max_depth,
        max_subagents=max_subagents,
        max_retries=max_retries,
        max_tokens_or_compute_units=max_tokens,
        expires_at=expires_at or future_ts(),
        validator_required=True,
        promotion_target=promotion_target,
        allowed_tools=["read", "grep"],
        allowed_data_sources=["internal_db"],
    )


def make_root_envelope(task_id: str = None) -> RootBudgetEnvelope:
    return RootBudgetEnvelope(
        root_budget_envelope_id=str(uuid.uuid4()),
        task_id=task_id or str(uuid.uuid4()),
        max_total_tokens_or_compute_units=100_000,
        max_total_subagents=20,
        max_total_wallclock=7200,
        max_total_external_calls=50,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )


def make_run(
    conn,
    task_id: str,
    role: str = "executor",
    status: str = "running",
    expires_in: int = 3600,
) -> Run:
    from orchestrator.repositories.run_repository import RunRepository
    repo = RunRepository(conn)
    run = Run(
        run_id=str(uuid.uuid4()),
        task_id=task_id,
        work_item_id=None,
        role=role,
        status=status,
        started_at=datetime.now(tz=timezone.utc).isoformat(),
        expires_at=future_ts(expires_in),
        attempt_no=1,
        parent_run_id=None,
    )
    return repo.create_run(run)


def make_validator_result(
    conn,
    task_id: str,
    run_id: str,
    status: str = ValidationStatus.PASS,
) -> ValidatorResult:
    from orchestrator.repositories.validator_repository import ValidatorRepository
    repo = ValidatorRepository(conn)
    result = ValidatorResult(
        validator_result_id=str(uuid.uuid4()),
        task_id=task_id,
        run_id=run_id,
        validation_status=status,
        confidence_score=0.95,
        failed_constraints=[],
        grounding_status="GROUNDED",
        schema_status="VALID",
        policy_status="COMPLIANT",
        remediation_action=None,
        notes=None,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    return repo.create_result(result)


def make_promotion_record(
    conn,
    task_id: str,
    validation_result_id: str,
    source_artifact_id: str = None,
) -> PromotionRecord:
    record = PromotionRecord(
        promotion_record_id=str(uuid.uuid4()),
        task_id=task_id,
        source_layer="proposal",
        target_layer="durable",
        source_artifact_id=source_artifact_id,
        target_object_id=None,
        executor_id="executor-001",
        validator_id="validator-001",
        validation_result_id=validation_result_id,
        approval_metadata=None,
        artifact_input_hash=None,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    conn.execute(
        """
        INSERT INTO promotion_records (
            promotion_record_id, task_id, source_layer, target_layer,
            source_artifact_id, target_object_id,
            executor_id, validator_id, validation_result_id,
            approval_metadata, artifact_input_hash, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.promotion_record_id, record.task_id,
            record.source_layer, record.target_layer,
            record.source_artifact_id, record.target_object_id,
            record.executor_id, record.validator_id,
            record.validation_result_id, record.approval_metadata,
            record.artifact_input_hash, record.timestamp,
        ),
    )
    conn.commit()
    return record
