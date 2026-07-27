"""
Intake stub for workflow_001_grounded_internal_synthesis.

Responsibilities:
- Normalize operator request to IntakeResult
- Validate that source_artifact_refs are present (workflow_001 requires them)
- Set ambiguity flags for soft issues
- Does NOT plan, execute, or read validator histories
- Does NOT mutate durable state

If source_artifact_refs are absent, raises IntakeError immediately.
This is a hard contract requirement for workflow_001.
"""
from __future__ import annotations

import uuid
from typing import List

from orchestrator.models.workflow import IntakeResult


class IntakeError(Exception):
    """Raised when the operator request cannot be normalized into a valid IntakeResult."""


_KNOWN_TASK_TYPES = {"grounded_internal_synthesis", "summary", "analysis"}
_KNOWN_OUTPUT_TYPES = {"synthesis_result", "summary", "report"}
_DEFAULT_TASK_TYPE = "grounded_internal_synthesis"
_DEFAULT_OUTPUT_TYPE = "synthesis_result"


def normalize(
    raw_request: dict,
    source_artifact_refs: List[str],
    task_family_config: dict,
) -> IntakeResult:
    """
    Normalize an operator request into an IntakeResult.

    Raises IntakeError if:
    - source_artifact_refs is empty or missing (workflow_001 hard requirement)
    - raw_request is not a dict

    Sets ambiguity_flags for soft issues (unknown task_type, missing fields).
    """
    if not isinstance(raw_request, dict):
        raise IntakeError(
            f"raw_request must be a dict; got {type(raw_request).__name__!r}"
        )

    # Hard requirement for workflow_001: source refs must be present
    if not source_artifact_refs:
        raise IntakeError(
            "workflow_001_grounded_internal_synthesis requires at least one "
            "source_artifact_ref. None provided. "
            "Provide approved internal source artifact IDs in source_artifact_refs."
        )

    ambiguity_flags: List[str] = []

    # Normalize task_type
    raw_task_type = raw_request.get("task_type") or task_family_config.get("task_type", "")
    if raw_task_type in _KNOWN_TASK_TYPES:
        normalized_task_type = raw_task_type
    else:
        normalized_task_type = _DEFAULT_TASK_TYPE
        if raw_task_type:
            ambiguity_flags.append(f"unknown_task_type:{raw_task_type!r}; defaulted to {_DEFAULT_TASK_TYPE!r}")
        else:
            ambiguity_flags.append("task_type_not_specified; defaulted to grounded_internal_synthesis")

    # Normalize criticality
    criticality_level = (
        raw_request.get("criticality_level")
        or task_family_config.get("criticality_level", "standard")
    )

    # Normalize output type
    requested_output_type = (
        raw_request.get("requested_output_type")
        or task_family_config.get("requested_output_type", _DEFAULT_OUTPUT_TYPE)
    )
    if requested_output_type not in _KNOWN_OUTPUT_TYPES:
        ambiguity_flags.append(
            f"unknown_output_type:{requested_output_type!r}; will be validated downstream"
        )

    task_family = task_family_config.get("task_family", "workflow_001")

    return IntakeResult(
        request_id=raw_request.get("request_id") or str(uuid.uuid4()),
        raw_request=raw_request,
        source_artifact_refs=list(source_artifact_refs),
        normalized_task_type=normalized_task_type,
        criticality_level=criticality_level,
        requested_output_type=requested_output_type,
        task_family=task_family,
        ambiguity_flags=ambiguity_flags,
    )
