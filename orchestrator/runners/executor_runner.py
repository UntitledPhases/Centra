"""
Executor runner — PROPOSAL + EPHEMERAL partition writer.

Responsibilities:
- Create the executor Run record
- Emit heartbeats (start, completion)
- Call ExecutorAdapter (no network calls in this move)
- Write proposed artifacts and optional observations to proposal layer
- Update run status
- Return (Run, ExecutorOutput)

Does NOT validate. Does NOT write durable state. Does NOT read validator histories.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from orchestrator.adapters.protocols import ExecutorAdapter
from orchestrator.context import RepoContext
from orchestrator.models.run import Run
from orchestrator.models.workflow import ExecutorOutput, PlannedTask


def execute(
    planned_task: PlannedTask,
    repos: RepoContext,
    adapter: ExecutorAdapter,
    attempt_no: int = 1,
    parent_run_id: Optional[str] = None,
) -> tuple[Run, ExecutorOutput]:
    """
    Execute one work item attempt via the adapter.

    Returns (executor_run, executor_output).
    The run will have status='completed' even if the adapter returns malformed output,
    because "completed" means the runner finished its cycle — the validator
    determines whether the output is acceptable.
    """
    now = datetime.now(tz=timezone.utc)
    run_id = str(uuid.uuid4())

    run = Run(
        run_id=run_id,
        task_id=planned_task.task_id,
        work_item_id=planned_task.work_item_record.work_item_id,
        role="executor",
        status="running",
        started_at=now.isoformat(),
        expires_at=planned_task.task_record.expires_at,
        attempt_no=attempt_no,
        parent_run_id=parent_run_id,
    )
    repos.run_repo.create_run(run)
    repos.run_repo.record_heartbeat(run_id, "running", f"attempt {attempt_no} started")

    # Call adapter — no network in this move; fake adapters return synchronously
    adapter_result = adapter.execute(
        work_item=planned_task.work_item_record,
        source_artifact_refs=planned_task.work_item_record.input_artifact_refs or [],
        context={
            "task_id": planned_task.task_id,
            "attempt_no": attempt_no,
            "allowed_tools": planned_task.allowed_tools,
        },
    )

    # Write proposed artifact to proposal layer
    proposed_artifact_ref: Optional[str] = None
    if adapter_result.content:
        artifact_id = str(uuid.uuid4())
        repos.proposal_repo.create_proposed_artifact(
            artifact_id=artifact_id,
            task_id=planned_task.task_id,
            artifact_type=adapter_result.artifact_type,
            content=adapter_result.content,
            run_id=run_id,
            schema_valid=adapter_result.schema_valid,
        )
        proposed_artifact_ref = artifact_id

    # Write proposed observation if adapter produced one
    proposed_observation_refs: List[str] = []
    if adapter_result.observation_content:
        obs_id = str(uuid.uuid4())
        # Hash the observation content to get content_hash
        import hashlib
        obs_hash = hashlib.sha256(adapter_result.observation_content).hexdigest()
        repos.proposal_repo.create_proposed_observation(
            observation_id=obs_id,
            task_id=planned_task.task_id,
            content_hash=obs_hash,
            artifact_id=proposed_artifact_ref,
        )
        proposed_observation_refs.append(obs_id)

    # Mark run completed and emit final heartbeat
    repos.run_repo.update_status(run_id, "completed")
    repos.run_repo.record_heartbeat(
        run_id,
        "completed",
        f"attempt {attempt_no} finished; "
        f"declared_status={adapter_result.declared_completion_status!r}; "
        f"schema_valid={adapter_result.schema_valid}",
    )

    executor_output = ExecutorOutput(
        run_id=run_id,
        task_id=planned_task.task_id,
        work_item_id=planned_task.work_item_record.work_item_id,
        proposed_artifact_ref=proposed_artifact_ref,
        proposed_observation_refs=proposed_observation_refs,
        declared_completion_status=adapter_result.declared_completion_status,
        self_check=adapter_result.self_check,
    )

    return run, executor_output
