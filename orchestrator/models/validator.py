"""Validator result model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class ValidationStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    ESCALATE = "ESCALATE"

    _PROMOTABLE = {"PASS"}
    _BLOCKING   = {"FAIL", "ESCALATE"}

    @classmethod
    def is_promotable(cls, status: str) -> bool:
        return status in cls._PROMOTABLE

    @classmethod
    def is_blocking(cls, status: str) -> bool:
        return status in cls._BLOCKING


@dataclass
class ValidatorResult:
    validator_result_id: str
    task_id: str
    run_id: str
    validation_status: str          # 'PASS' | 'FAIL' | 'ESCALATE'
    confidence_score: Optional[float]
    failed_constraints: List[str]
    grounding_status: str
    schema_status: str
    policy_status: str
    remediation_action: Optional[str]
    notes: Optional[str]
    created_at: str
