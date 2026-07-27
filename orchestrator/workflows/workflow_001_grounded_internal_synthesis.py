"""
workflow_001_grounded_internal_synthesis

Narrow, lawful control-flow for:
  one operator request → one task → one executor run → deterministic validation
  → validator result → if PASS: promotion → durable rows
  → completion result

Contract:
- Intake normalizes the request; missing source_artifact_refs fails immediately.
- Planner creates task + root_budget_envelope + work_item through repositories.
- Executor runner produces proposal-state; no durable writes.
- Validator runner runs deterministic checks first; adapter called only if they pass.
- PASS → promoter path (via existing promotion_repo + durable_repo with role='promoter').
- FAIL/ESCALATE/deterministic invalidity → no promotion.
- Stale/zombie/expired executor run → PromotionBlockedError caught → DEAD_LETTERED.
- Retry: at most once if max_retries > 0 and failure class is retryable.
- Synthesizer: not implemented; reserved future boundary.

DO NOT add external API calls, maintenance mode, or synthesizer logic here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from orchestrator import intake as _intake
from orchestrator import planner as _planner
from orchestrator.adapters.protocols import ExecutorAdapter, ValidatorAdapter
from orchestrator.context import RepoContext
from orchestrator.intake import IntakeError
from orchestrator.models.dead_letter import DeadLetterEntry
from orchestrator.models.promotion import PromotionRecord
from orchestrator.models.run import Run
from orchestrator.models.validator import ValidationStatus, ValidatorResult
from orchestrator.models.workflow import (
    ExecutorOutput,
    PlannedTask,
    WorkflowCompletionResult,
)
from orchestrator.repositories.promotion_repository import PromotionBlockedError
from orchestrator.runners import executor_runner, validator_runner
from orchestrator.runners.validator_runner import RETRYABLE_FAILURE_CLASSES


_WORKFLOW_ID = "workflow_001_grounded_internal_synthesis"
_EXECUTOR_IDENTITY = "executor:workflow_001"
_VALIDATOR_IDENTITY = "validator:workflow_001"


def run(
    operator_request: dict,
    source_artifact_refs: List[str],
    task_family_config: dict,
    root_budget_input: dict,
    repos: RepoContext,
    executor_adapter: ExecutorAdapter,
    validator_adapter: ValidatorAdapter,
    max_retries: int = 0,
    stale_threshold_seconds: int = 300,
) -> WorkflowCompletionResult:
    """
    Execute workflow_001 end-to-end.

    max_retries:
      0 (default) — no retry; malformed executor output → DEAD_LETTERED immediately.
      1            — one retry for retryable deterministic failures only.
      Values > 1 are treated as 1 (spec: at most one retry).

    stale_threshold_seconds:
      Passed to promotion_repo for executor run liveness check.
      Default 300 (5 min). Set to 0 in tests to force staleness detection.
    """
    # Clamp retry to at most 1 as per spec
    effective_max_retries = min(max_retries, 1)
    max_attempts = effective_max_retries + 1

    # ----------------------------------------------------------------
    # Step 1: Intake
    # ----------------------------------------------------------------
    try:
        intake_result = _intake.normalize(
            raw_request=operator_request,
            source_artifact_refs=source_artifact_refs,
            task_family_config=task_family_config,
        )
    except IntakeError as exc:
        dl = _create_dead_letter(
            repos=repos,
            task_id=None,
            run_id=None,
            failure_class="INTAKE_ERROR",
            reason=str(exc),
        )
        return WorkflowCompletionResult(
            task_id="",
            final_status="DEAD_LETTERED",
            promotion_record_id=None,
            approved_artifact_ids=[],
            validated_observation_ids=[],
            dead_letter_id=dl.dead_letter_id,
            blocking_reason=str(exc),
        )

    # ----------------------------------------------------------------
    # Step 2: Plan (creates task + root_budget_envelope + work_item)
    # ----------------------------------------------------------------
    planned_task = _planner.plan(
        intake_result=intake_result,
        root_budget_input=root_budget_input,
        repos=repos,
    )

    # ----------------------------------------------------------------
    # Steps 3-4: Execute + Validate (with retry loop)
    # ----------------------------------------------------------------
    last_executor_run: Optional[Run] = None
    last_executor_output: Optional[ExecutorOutput] = None
    last_validator_result: Optional[ValidatorResult] = None
    last_det_failure_class: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        parent_run_id = last_executor_run.run_id if last_executor_run is not None else None
        exec_run, exec_output = executor_runner.execute(
            planned_task=planned_task,
            repos=repos,
            adapter=executor_adapter,
            attempt_no=attempt,
            parent_run_id=parent_run_id,
        )

        vr, det_failure_class = validator_runner.validate(
            executor_output=exec_output,
            executor_run=exec_run,
            planned_task=planned_task,
            source_artifact_refs=intake_result.source_artifact_refs,
            repos=repos,
            adapter=validator_adapter,
        )

        last_executor_run = exec_run
        last_executor_output = exec_output
        last_validator_result = vr
        last_det_failure_class = det_failure_class

        # Retry only when: deterministic failure + retryable class + attempts remain
        should_retry = (
            vr.validation_status == ValidationStatus.FAIL
            and det_failure_class is not None
            and det_failure_class in RETRYABLE_FAILURE_CLASSES
            and attempt < max_attempts
        )
        if not should_retry:
            break

    # ----------------------------------------------------------------
    # Step 5: Route on final validator result
    # ----------------------------------------------------------------
    assert last_validator_result is not None
    assert last_executor_run is not None
    assert last_executor_output is not None

    if last_validator_result.validation_status == ValidationStatus.PASS:
        return _promoter_path(
            executor_run=last_executor_run,
            executor_output=last_executor_output,
            planned_task=planned_task,
            validator_result=last_validator_result,
            repos=repos,
            stale_threshold_seconds=stale_threshold_seconds,
        )

    if last_validator_result.validation_status == ValidationStatus.ESCALATE:
        return WorkflowCompletionResult(
            task_id=planned_task.task_id,
            final_status="ESCALATED",
            promotion_record_id=None,
            approved_artifact_ids=[],
            validated_observation_ids=[],
            dead_letter_id=None,
            blocking_reason=(
                f"Validator returned ESCALATE. "
                f"Notes: {last_validator_result.notes}"
            ),
        )

    # FAIL (or any other non-PASS non-ESCALATE status)
    reason = (
        f"Validator returned {last_validator_result.validation_status}. "
        f"Failure class: {last_det_failure_class or 'ADAPTER_FAIL'}. "
        f"Constraints: {last_validator_result.failed_constraints}."
    )
    failure_class = last_det_failure_class or "VALIDATION_FAIL"
    dl = _create_dead_letter(
        repos=repos,
        task_id=planned_task.task_id,
        run_id=last_executor_run.run_id,
        failure_class=failure_class,
        reason=reason,
    )
    return WorkflowCompletionResult(
        task_id=planned_task.task_id,
        final_status="DEAD_LETTERED",
        promotion_record_id=None,
        approved_artifact_ids=[],
        validated_observation_ids=[],
        dead_letter_id=dl.dead_letter_id,
        blocking_reason=reason,
    )


# ------------------------------------------------------------------
# Promoter path — the ONLY place in this workflow that touches durable state
# ------------------------------------------------------------------

def _promoter_path(
    executor_run: Run,
    executor_output: ExecutorOutput,
    planned_task: PlannedTask,
    validator_result: ValidatorResult,
    repos: RepoContext,
    stale_threshold_seconds: int,
) -> WorkflowCompletionResult:
    """
    Create promotion record + durable rows.
    Uses existing promotion_repo and durable_repo (with role='promoter').
    All enforcement (PASS-only, stale/zombie, FK linkage) is inside those repos.
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        prec = PromotionRecord(
            promotion_record_id=str(uuid.uuid4()),
            task_id=planned_task.task_id,
            source_layer="proposal",
            target_layer="durable",
            source_artifact_id=executor_output.proposed_artifact_ref,
            target_object_id=None,
            executor_id=_EXECUTOR_IDENTITY,
            validator_id=_VALIDATOR_IDENTITY,
            validation_result_id=validator_result.validator_result_id,
            approval_metadata=None,
            artifact_input_hash=None,
            timestamp=now,
        )

        prec = repos.promotion_repo.create_promotion_record(
            prec,
            executor_run_id=executor_run.run_id,
            stale_threshold_seconds=stale_threshold_seconds,
        )

        # Promote artifact to durable layer — role must be 'promoter'
        approved_artifact_ids: List[str] = []
        if executor_output.proposed_artifact_ref is not None:
            approved_id = str(uuid.uuid4())
            repos.durable_repo.promote_artifact(
                role="promoter",
                approved_artifact_id=approved_id,
                source_artifact_id=executor_output.proposed_artifact_ref,
                promotion_record_id=prec.promotion_record_id,
            )
            approved_artifact_ids.append(approved_id)

        # Promote observations if any (minimal — obs promotion is complete but optional)
        validated_obs_ids: List[str] = []
        for obs_id in executor_output.proposed_observation_refs:
            obs = repos.proposal_repo.get_proposed_observation(obs_id)
            if obs is not None:
                vobs_id = str(uuid.uuid4())
                repos.durable_repo.promote_observation(
                    role="promoter",
                    validated_observation_id=vobs_id,
                    source_observation_id=obs_id,
                    promotion_record_id=prec.promotion_record_id,
                    content_hash=obs["content_hash"],
                )
                validated_obs_ids.append(vobs_id)

        return WorkflowCompletionResult(
            task_id=planned_task.task_id,
            final_status="PROMOTED",
            promotion_record_id=prec.promotion_record_id,
            approved_artifact_ids=approved_artifact_ids,
            validated_observation_ids=validated_obs_ids,
            dead_letter_id=None,
            blocking_reason=None,
        )

    except PromotionBlockedError as exc:
        reason = str(exc)
        dl = _create_dead_letter(
            repos=repos,
            task_id=planned_task.task_id,
            run_id=executor_run.run_id,
            failure_class="PROMOTION_BLOCKED",
            reason=reason,
        )
        return WorkflowCompletionResult(
            task_id=planned_task.task_id,
            final_status="DEAD_LETTERED",
            promotion_record_id=None,
            approved_artifact_ids=[],
            validated_observation_ids=[],
            dead_letter_id=dl.dead_letter_id,
            blocking_reason=reason,
        )


# ------------------------------------------------------------------
# Dead-letter helper
# ------------------------------------------------------------------

def _create_dead_letter(
    repos: RepoContext,
    task_id: Optional[str],
    run_id: Optional[str],
    failure_class: str,
    reason: str,
    retry_count: int = 0,
) -> DeadLetterEntry:
    entry = DeadLetterEntry(
        dead_letter_id=str(uuid.uuid4()),
        task_id=task_id,
        run_id=run_id,
        failure_class=failure_class,
        reason=reason,
        retry_count=retry_count,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    return repos.dead_letter_repo.create_entry(entry)
