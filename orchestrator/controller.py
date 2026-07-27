"""
Controller — minimal, not a general orchestration framework.

Public surface:
  Controller.submit(request) -> WorkflowCompletionResult

The controller:
- accepts a SubmitRequest
- delegates to workflow_001 via its run() function
- returns a WorkflowCompletionResult

The controller does NOT:
- write durable rows directly (no INSERT INTO approved_artifacts here)
- hold a reference to durable_repo for direct use
- implement routing, reputation, or generalized scheduling
- call any repository SQL directly
- implement synthesizer logic (reserved future boundary)

All enforcement (PASS-only, stale/zombie, FK linkage) lives in the
existing repositories and guards — the controller just calls workflow_001.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from orchestrator.adapters.protocols import ExecutorAdapter, ValidatorAdapter
from orchestrator.context import RepoContext
from orchestrator.models.workflow import WorkflowCompletionResult
from orchestrator.workflows import workflow_001_grounded_internal_synthesis as workflow_001


@dataclass
class SubmitRequest:
    """
    Operator request submitted to the controller.
    All fields are passed through to workflow_001 without interpretation.
    """
    operator_request: dict
    source_artifact_refs: List[str]
    task_family_config: dict
    root_budget_input: dict
    max_retries: int = 0
    stale_threshold_seconds: int = 300


class Controller:
    """
    Thin dispatch layer over workflow_001.

    Receives repos (pre-wired) and adapters (injected, pluggable).
    Does not hold durable_repo for direct use — repos are passed to workflow_001.
    """

    def __init__(
        self,
        repos: RepoContext,
        executor_adapter: ExecutorAdapter,
        validator_adapter: ValidatorAdapter,
    ) -> None:
        self._repos = repos
        self._executor_adapter = executor_adapter
        self._validator_adapter = validator_adapter

    def submit(self, request: SubmitRequest) -> WorkflowCompletionResult:
        """
        Run workflow_001 for the given operator request.
        Returns a WorkflowCompletionResult with final_status in
        {PROMOTED, ESCALATED, DEAD_LETTERED}.
        """
        return workflow_001.run(
            operator_request=request.operator_request,
            source_artifact_refs=request.source_artifact_refs,
            task_family_config=request.task_family_config,
            root_budget_input=request.root_budget_input,
            repos=self._repos,
            executor_adapter=self._executor_adapter,
            validator_adapter=self._validator_adapter,
            max_retries=request.max_retries,
            stale_threshold_seconds=request.stale_threshold_seconds,
        )
