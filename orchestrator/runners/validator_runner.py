"""
Validator runner — EPHEMERAL partition writer.

Responsibilities:
- Run deterministic checks FIRST (schema shape, budget expiry, source refs, artifact validity)
- If any deterministic check fails → write FAIL validator_result; do NOT call adapter
- If all deterministic checks pass → call ValidatorAdapter
- Write validator_result via validator_repo
- Return (ValidatorResult, Optional[str]) where the second item is the
  deterministic_failure_class if deterministic checks blocked the adapter call,
  or None if the adapter was called.

INVARIANT: Deterministic invalidity cannot be overridden by adapter output.
The adapter is never called when deterministic checks fail.

Does NOT write durable state. Does NOT write proposal state.
Executor must not receive validator histories — this runner does not expose them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from orchestrator.adapters.protocols import ValidatorAdapter, ValidatorAdapterResult
from orchestrator.context import RepoContext
from orchestrator.models.run import Run
from orchestrator.models.validator import ValidatorResult, ValidationStatus
from orchestrator.models.workflow import ExecutorOutput, PlannedTask


# ------------------------------------------------------------------
# Deterministic failure classes
# ------------------------------------------------------------------

class DeterministicFailureClass:
    NO_ARTIFACT = "NO_ARTIFACT"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"   # schema_valid=False or bad completion status
    BUDGET_EXPIRED = "BUDGET_EXPIRED"
    MISSING_SOURCE_REFS = "MISSING_SOURCE_REFS"


# Retryable by workflow retry logic
RETRYABLE_FAILURE_CLASSES = frozenset({
    DeterministicFailureClass.NO_ARTIFACT,
    DeterministicFailureClass.MALFORMED_OUTPUT,
})

# Valid declared completion statuses from executor
_VALID_COMPLETION_STATUSES = frozenset({"completed"})


def validate(
    executor_output: ExecutorOutput,
    executor_run: Run,
    planned_task: PlannedTask,
    source_artifact_refs: List[str],
    repos: RepoContext,
    adapter: ValidatorAdapter,
) -> Tuple[ValidatorResult, Optional[str]]:
    """
    Run validation and write the ValidatorResult.

    Returns:
      (ValidatorResult, None)                if adapter was called (pass-through result)
      (ValidatorResult(FAIL), failure_class) if deterministic checks blocked the adapter
    """
    now = datetime.now(tz=timezone.utc)

    # Create a validator run for this validation cycle
    validator_run_id = str(uuid.uuid4())
    from orchestrator.models.run import Run as RunModel
    validator_run = RunModel(
        run_id=validator_run_id,
        task_id=planned_task.task_id,
        work_item_id=None,
        role="validator",
        status="running",
        started_at=now.isoformat(),
        expires_at=planned_task.task_record.expires_at,
        attempt_no=executor_run.attempt_no,
        parent_run_id=executor_run.run_id,
    )
    repos.run_repo.create_run(validator_run)
    repos.run_repo.record_heartbeat(validator_run_id, "running", "deterministic checks starting")

    # ------------------------------------------------------------------
    # DETERMINISTIC CHECKS — adapter is never called if these fail
    # ------------------------------------------------------------------
    det_failures: List[str] = []
    det_failure_class: Optional[str] = None

    # Check 1: source_artifact_refs required by workflow_001
    if not source_artifact_refs:
        det_failures.append("workflow_001 requires source_artifact_refs; none provided")
        det_failure_class = DeterministicFailureClass.MISSING_SOURCE_REFS

    # Check 2: artifact was produced
    if executor_output.proposed_artifact_ref is None:
        det_failures.append("executor produced no artifact (proposed_artifact_ref is None)")
        det_failure_class = det_failure_class or DeterministicFailureClass.NO_ARTIFACT

    # Check 3: declared completion status valid
    elif executor_output.declared_completion_status not in _VALID_COMPLETION_STATUSES:
        det_failures.append(
            f"declared_completion_status {executor_output.declared_completion_status!r} "
            f"is not in valid set {sorted(_VALID_COMPLETION_STATUSES)}"
        )
        det_failure_class = det_failure_class or DeterministicFailureClass.MALFORMED_OUTPUT

    # Check 4: schema_valid from proposed artifact row
    if executor_output.proposed_artifact_ref is not None:
        artifact = repos.proposal_repo.get_proposed_artifact(executor_output.proposed_artifact_ref)
        if artifact is None:
            det_failures.append(
                f"proposed artifact {executor_output.proposed_artifact_ref!r} not found in proposal layer"
            )
            det_failure_class = det_failure_class or DeterministicFailureClass.NO_ARTIFACT
        elif not artifact.schema_valid:
            det_failures.append(
                f"proposed artifact {executor_output.proposed_artifact_ref!r} has schema_valid=False"
            )
            det_failure_class = det_failure_class or DeterministicFailureClass.MALFORMED_OUTPUT

    # Check 5: task budget not expired
    try:
        from datetime import datetime as _dt, timezone as _tz
        expiry = _dt.fromisoformat(
            planned_task.task_record.expires_at.replace("Z", "+00:00")
        )
        if _dt.now(tz=_tz.utc) >= expiry:
            det_failures.append(
                f"task budget is expired (expires_at={planned_task.task_record.expires_at!r})"
            )
            det_failure_class = det_failure_class or DeterministicFailureClass.BUDGET_EXPIRED
    except ValueError:
        det_failures.append(
            f"task has invalid expires_at: {planned_task.task_record.expires_at!r}"
        )
        det_failure_class = det_failure_class or DeterministicFailureClass.BUDGET_EXPIRED

    # ------------------------------------------------------------------
    # If deterministic checks failed → write FAIL, do NOT call adapter
    # ------------------------------------------------------------------
    if det_failures:
        vr = _write_validator_result(
            repos=repos,
            task_id=planned_task.task_id,
            run_id=validator_run_id,
            status=ValidationStatus.FAIL,
            failed_constraints=det_failures,
            grounding_status="UNVERIFIED",
            schema_status="INVALID",
            policy_status="UNCHECKED",
            confidence_score=0.0,
            notes=f"Deterministic checks failed ({det_failure_class}). Adapter not called.",
        )
        repos.run_repo.update_status(validator_run_id, "completed")
        repos.run_repo.record_heartbeat(
            validator_run_id, "completed",
            f"deterministic FAIL: {det_failure_class}"
        )
        return vr, det_failure_class

    # ------------------------------------------------------------------
    # Deterministic checks passed → call adapter
    # ------------------------------------------------------------------
    try:
        artifact_content = repos.proposal_repo.get_proposed_artifact_content(
            executor_output.proposed_artifact_ref
        )
    except FileNotFoundError as exc:
        # Shouldn't happen after check 4, but guard defensively
        vr = _write_validator_result(
            repos=repos,
            task_id=planned_task.task_id,
            run_id=validator_run_id,
            status=ValidationStatus.FAIL,
            failed_constraints=[str(exc)],
            grounding_status="UNVERIFIED",
            schema_status="MISSING",
            policy_status="UNCHECKED",
            confidence_score=0.0,
            notes="Artifact disappeared between deterministic check and adapter call.",
        )
        repos.run_repo.update_status(validator_run_id, "completed")
        repos.run_repo.record_heartbeat(validator_run_id, "completed", "artifact missing at adapter call")
        return vr, DeterministicFailureClass.NO_ARTIFACT

    adapter_result: ValidatorAdapterResult = adapter.validate(
        executor_output=executor_output,
        artifact_content=artifact_content,
        source_refs=source_artifact_refs,
        context={
            "task_id": planned_task.task_id,
            "validator_run_id": validator_run_id,
        },
    )

    vr = _write_validator_result(
        repos=repos,
        task_id=planned_task.task_id,
        run_id=validator_run_id,
        status=adapter_result.validation_status,
        failed_constraints=adapter_result.failed_constraints,
        grounding_status=adapter_result.grounding_status,
        schema_status=adapter_result.schema_status,
        policy_status=adapter_result.policy_status,
        confidence_score=adapter_result.confidence_score,
        notes=adapter_result.notes,
        remediation_action=adapter_result.remediation_action,
    )
    repos.run_repo.update_status(validator_run_id, "completed")
    repos.run_repo.record_heartbeat(
        validator_run_id, "completed",
        f"adapter result: {adapter_result.validation_status}"
    )
    return vr, None   # None = adapter was called; no deterministic failure class


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _write_validator_result(
    repos: RepoContext,
    task_id: str,
    run_id: str,
    status: str,
    failed_constraints: List[str],
    grounding_status: str,
    schema_status: str,
    policy_status: str,
    confidence_score: float,
    notes: Optional[str] = None,
    remediation_action: Optional[str] = None,
) -> ValidatorResult:
    result = ValidatorResult(
        validator_result_id=str(uuid.uuid4()),
        task_id=task_id,
        run_id=run_id,
        validation_status=status,
        confidence_score=confidence_score,
        failed_constraints=failed_constraints,
        grounding_status=grounding_status,
        schema_status=schema_status,
        policy_status=policy_status,
        remediation_action=remediation_action,
        notes=notes,
        created_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    return repos.validator_repo.create_result(result)
