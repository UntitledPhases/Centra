"""
Adapter protocols for the executor and validator roles.

These define the boundary between the orchestration kernel and any model
or compute backend. No real network calls are made in this module.

For slice-1 / move-3, only fake adapters exist. Real adapters are deferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable

from orchestrator.models.task import WorkItem
from orchestrator.models.workflow import ExecutorOutput


# ------------------------------------------------------------------
# Adapter result types
# ------------------------------------------------------------------

@dataclass
class ExecutorAdapterResult:
    """
    Raw output from an executor adapter.
    schema_valid and declared_completion_status are used by the deterministic
    validator to gate promotion — the adapter cannot override these flags once
    deterministic checks run.
    """
    content: bytes                              # raw artifact bytes
    artifact_type: str                          # e.g. 'synthesis_result'
    schema_valid: bool                          # deterministic validity signal
    declared_completion_status: str             # 'completed' | 'failed' | other
    self_check: str                             # advisory; never gates promotion
    observation_content: Optional[bytes] = None # optional inline observation


@dataclass
class ValidatorAdapterResult:
    """
    Raw output from a validator adapter.
    Called ONLY after deterministic checks pass. If deterministic checks fail,
    this type is never produced.
    """
    validation_status: str                      # 'PASS' | 'FAIL' | 'ESCALATE'
    confidence_score: float
    failed_constraints: List[str] = field(default_factory=list)
    grounding_status: str = "GROUNDED"
    schema_status: str = "VALID"
    policy_status: str = "COMPLIANT"
    remediation_action: Optional[str] = None
    notes: Optional[str] = None


# ------------------------------------------------------------------
# Adapter protocols
# ------------------------------------------------------------------

@runtime_checkable
class ExecutorAdapter(Protocol):
    """
    Pluggable executor backend.
    Receives a work item and source artifact refs; returns a raw result.
    Must not write to any repository — that is the runner's job.
    """

    def execute(
        self,
        work_item: WorkItem,
        source_artifact_refs: List[str],
        context: dict,
    ) -> ExecutorAdapterResult:
        ...


@runtime_checkable
class ValidatorAdapter(Protocol):
    """
    Pluggable validator backend.
    Receives executor output and artifact content; returns a validation result.
    Called ONLY when all deterministic checks have passed.
    Must not write to any repository.
    """

    def validate(
        self,
        executor_output: ExecutorOutput,
        artifact_content: bytes,
        source_refs: List[str],
        context: dict,
    ) -> ValidatorAdapterResult:
        ...
