"""
Data contracts for workflow_001 control-flow.

These are narrow, local types used between controller, intake, planner,
runners, and the workflow function. They are not persisted directly;
the underlying repositories hold the ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from orchestrator.models.task import Task, WorkItem


@dataclass
class IntakeResult:
    """Normalized output of the intake step. Immutable after creation."""
    request_id: str
    raw_request: dict
    source_artifact_refs: List[str]
    normalized_task_type: str
    criticality_level: str
    requested_output_type: str
    task_family: str
    ambiguity_flags: List[str]


@dataclass
class PlannedTask:
    """
    Output of the planner step.
    Carries live repo objects (Task, WorkItem, envelope id) so downstream steps
    can reference them without re-querying.
    """
    task_id: str
    root_budget_envelope_id: str
    task_record: Task
    work_item_record: WorkItem
    allowed_tools: List[str]
    allowed_data_sources: List[str]
    validator_required: bool
    promotion_target: str


@dataclass
class ExecutorOutput:
    """
    Ephemeral output from the executor runner.
    References proposal-layer IDs, not durable IDs.
    """
    run_id: str
    task_id: str
    work_item_id: str
    proposed_artifact_ref: Optional[str]    # artifact_id in proposal layer; None = no artifact
    proposed_observation_refs: List[str]    # observation_ids in proposal layer
    declared_completion_status: str         # 'completed' | 'failed' | other
    self_check: str                         # advisory; does not affect promotion


@dataclass
class WorkflowCompletionResult:
    """
    Terminal result returned by workflow_001 and the controller.

    final_status values:
      PROMOTED      — validator PASS + durable rows created
      FAILED        — (not used currently; kept for future differentiation)
      ESCALATED     — validator ESCALATE; no durable rows
      DEAD_LETTERED — any terminal failure; dead_letter_entry created
    """
    task_id: str
    final_status: str                       # PROMOTED | ESCALATED | DEAD_LETTERED
    promotion_record_id: Optional[str]
    approved_artifact_ids: List[str]
    validated_observation_ids: List[str]
    dead_letter_id: Optional[str]
    blocking_reason: Optional[str]
