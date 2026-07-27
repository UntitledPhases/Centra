"""Task and WorkItem models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Task:
    task_id: str
    parent_task_id: Optional[str]
    task_type: str
    criticality_level: str
    status: str
    promotion_target: str
    # Budget header fields (embedded)
    max_depth: int
    max_subagents: int
    max_retries: int
    max_tokens_or_compute_units: int
    validator_required: bool
    allowed_tools: List[str]
    allowed_data_sources: List[str]
    maintenance_ticket_id: Optional[str]
    created_at: str
    expires_at: str


@dataclass
class WorkItem:
    work_item_id: str
    task_id: str
    assigned_role: str      # 'executor' | 'validator' | 'promoter'
    instructions: str
    input_artifact_refs: List[str]
    output_schema_ref: Optional[str]
    attempt_no: int
    created_at: str
