"""Promotion record and durable layer models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PromotionRecord:
    promotion_record_id: str
    task_id: str
    source_layer: str
    target_layer: str
    source_artifact_id: Optional[str]
    target_object_id: Optional[str]
    executor_id: str
    validator_id: str
    validation_result_id: str       # NOT NULL — enforced
    approval_metadata: Optional[str]
    artifact_input_hash: Optional[str]
    timestamp: str


@dataclass
class ValidatedObservation:
    validated_observation_id: str
    source_observation_id: str
    promotion_record_id: str        # NOT NULL
    content_hash: str
    created_at: str


@dataclass
class AcceptedRunSummary:
    run_summary_id: str
    task_id: str
    promotion_record_id: str        # NOT NULL
    summary_artifact_id: str
    created_at: str
