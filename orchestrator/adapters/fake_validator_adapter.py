"""
Fake validator adapter for tests and local development.

Supports:
- configurable validation_status: PASS | FAIL | ESCALATE
- RaisesIfCalledValidatorAdapter for verifying deterministic-checks-first invariant
"""
from __future__ import annotations

from typing import List, Optional

from orchestrator.adapters.protocols import ValidatorAdapterResult
from orchestrator.models.workflow import ExecutorOutput


class FakeValidatorAdapter:
    """Returns a fixed validation status. Configurable per test."""

    def __init__(self, status: str = "PASS") -> None:
        if status not in ("PASS", "FAIL", "ESCALATE"):
            raise ValueError(f"Invalid status for FakeValidatorAdapter: {status!r}")
        self._status = status
        self.call_count: int = 0

    def validate(
        self,
        executor_output: ExecutorOutput,
        artifact_content: bytes,
        source_refs: List[str],
        context: dict,
    ) -> ValidatorAdapterResult:
        self.call_count += 1
        is_pass = self._status == "PASS"
        return ValidatorAdapterResult(
            validation_status=self._status,
            confidence_score=0.95 if is_pass else 0.30,
            failed_constraints=[] if is_pass else ["constraint_violated"],
            grounding_status="GROUNDED",
            schema_status="VALID",
            policy_status="COMPLIANT",
            remediation_action=None if is_pass else "review output",
            notes=f"fake validator: {self._status}",
        )


class RaisesIfCalledValidatorAdapter:
    """
    Validator adapter that raises AssertionError if called.
    Use in tests to prove the validator adapter is never reached when
    deterministic checks fail (invariant: deterministic invalidity gates adapter call).
    """

    def validate(
        self,
        executor_output: ExecutorOutput,
        artifact_content: bytes,
        source_refs: List[str],
        context: dict,
    ) -> ValidatorAdapterResult:
        raise AssertionError(
            "ValidatorAdapter.validate() was called, but deterministic checks "
            "should have blocked this call. Invariant violated."
        )
