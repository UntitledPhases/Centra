"""
Planner stub for workflow_001.

Responsibilities:
- Create a lawful BudgetHeader from root_budget_input + intake_result
- Create the task via task_repo (which validates the budget header)
- Create the explicit root_budget_envelope via task_repo
- Create one work item for the executor role
- Return a PlannedTask

Does NOT execute work. Does NOT write durable state.
Does NOT read validator histories.

root_budget_input expected keys:
  max_total_tokens_or_compute_units  (int, required)
  max_total_subagents                (int, required)
  max_total_wallclock                (int, required, seconds)
  max_total_external_calls           (int, required)
  expires_in_seconds                 (int, required, determines task expires_at)
  max_retries                        (int, optional, default 0)
  criticality_level                  (str, optional, overrides intake)
  allowed_tools                      (list[str], optional)
  allowed_data_sources               (list[str], optional)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from orchestrator.context import RepoContext
from orchestrator.models.budget import BudgetHeader, RootBudgetEnvelope
from orchestrator.models.task import WorkItem
from orchestrator.models.workflow import IntakeResult, PlannedTask


class PlannerError(Exception):
    """Raised when the planner cannot produce a valid plan."""


_DEFAULT_ALLOWED_TOOLS = ["read", "grep", "proposal_write"]
_DEFAULT_ALLOWED_DATA_SOURCES = ["internal_approved_artifacts"]


def plan(
    intake_result: IntakeResult,
    root_budget_input: dict,
    repos: RepoContext,
) -> PlannedTask:
    """
    Create a task, root budget envelope, and work item from the intake result
    and root budget input. All writes go through the existing repositories
    (which enforce budget header completeness).

    Raises PlannerError if required root_budget_input fields are missing.
    May raise BudgetViolationError (from task_repo) if budget header is invalid.
    """
    _validate_root_budget_input(root_budget_input)

    task_id = str(uuid.uuid4())
    envelope_id = str(uuid.uuid4())
    work_item_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)

    expires_in = int(root_budget_input["expires_in_seconds"])
    expires_at = (now + timedelta(seconds=expires_in)).isoformat()

    allowed_tools: List[str] = (
        root_budget_input.get("allowed_tools") or _DEFAULT_ALLOWED_TOOLS
    )
    allowed_data_sources: List[str] = (
        root_budget_input.get("allowed_data_sources") or _DEFAULT_ALLOWED_DATA_SOURCES
    )
    criticality_level = (
        root_budget_input.get("criticality_level") or intake_result.criticality_level
    )
    max_retries = int(root_budget_input.get("max_retries", 0))

    # Budget header — validated by task_repo.create_task()
    budget_header = BudgetHeader(
        task_id=task_id,
        parent_task_id=None,  # root task for this workflow
        task_type=intake_result.normalized_task_type,
        criticality_level=criticality_level,
        max_depth=1,          # workflow_001 is depth-1: one executor, one validator
        max_subagents=2,      # executor + validator
        max_retries=max_retries,
        max_tokens_or_compute_units=root_budget_input["max_total_tokens_or_compute_units"],
        expires_at=expires_at,
        validator_required=True,
        promotion_target="durable",
        allowed_tools=allowed_tools,
        allowed_data_sources=allowed_data_sources,
        maintenance_ticket_id=None,
    )

    # Create task — budget guard runs inside create_task()
    task = repos.task_repo.create_task(budget_header)

    # Create root budget envelope — explicit, tied to root task
    envelope = RootBudgetEnvelope(
        root_budget_envelope_id=envelope_id,
        task_id=task_id,
        max_total_tokens_or_compute_units=root_budget_input["max_total_tokens_or_compute_units"],
        max_total_subagents=root_budget_input["max_total_subagents"],
        max_total_wallclock=root_budget_input["max_total_wallclock"],
        max_total_external_calls=root_budget_input["max_total_external_calls"],
        created_at=now.isoformat(),
    )
    repos.task_repo.create_root_budget_envelope(envelope)

    # Work item — one executor work item for this workflow
    work_item = WorkItem(
        work_item_id=work_item_id,
        task_id=task_id,
        assigned_role="executor",
        instructions=(
            f"Produce a grounded synthesis from the provided source artifacts. "
            f"Task type: {intake_result.normalized_task_type}. "
            f"Output type: {intake_result.requested_output_type}. "
            f"Source refs: {intake_result.source_artifact_refs}."
        ),
        input_artifact_refs=intake_result.source_artifact_refs,
        output_schema_ref=intake_result.requested_output_type,
        attempt_no=1,
        created_at=now.isoformat(),
    )
    repos.task_repo.create_work_item(work_item)

    return PlannedTask(
        task_id=task_id,
        root_budget_envelope_id=envelope_id,
        task_record=task,
        work_item_record=work_item,
        allowed_tools=allowed_tools,
        allowed_data_sources=allowed_data_sources,
        validator_required=True,
        promotion_target="durable",
    )


def _validate_root_budget_input(rbi: dict) -> None:
    required = (
        "max_total_tokens_or_compute_units",
        "max_total_subagents",
        "max_total_wallclock",
        "max_total_external_calls",
        "expires_in_seconds",
    )
    missing = [k for k in required if rbi.get(k) is None]
    if missing:
        raise PlannerError(
            f"root_budget_input is missing required fields: {missing}. "
            "All budget dimensions must be explicit."
        )
    if int(rbi["expires_in_seconds"]) <= 0:
        raise PlannerError(
            f"root_budget_input.expires_in_seconds must be > 0; "
            f"got {rbi['expires_in_seconds']!r}"
        )
