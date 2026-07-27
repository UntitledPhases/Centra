"""Budget header and root envelope models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# All fields required for a task budget header.
# Missing any field → task creation fails (validated in task_repository).
REQUIRED_BUDGET_FIELDS = (
    "task_id",
    "parent_task_id",   # None for root task (explicitly set to None, not missing)
    "task_type",
    "criticality_level",
    "max_depth",
    "max_subagents",
    "max_retries",
    "max_tokens_or_compute_units",
    "expires_at",
    "validator_required",
    "promotion_target",
    "allowed_tools",
    "allowed_data_sources",
    # maintenance_ticket_id is intentionally optional (no maintenance mode in slice-1)
)


@dataclass
class BudgetHeader:
    """Full budget header embedded in every task. All fields mandatory."""
    task_id: str
    parent_task_id: Optional[str]         # None for root task
    task_type: str
    criticality_level: str
    max_depth: int
    max_subagents: int
    max_retries: int
    max_tokens_or_compute_units: int
    expires_at: str                        # ISO-8601 UTC
    validator_required: bool
    promotion_target: str                  # 'durable' | 'proposal'
    allowed_tools: List[str]
    allowed_data_sources: List[str]
    maintenance_ticket_id: Optional[str] = None

    def as_dict(self) -> dict:
        import json
        return {
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "task_type": self.task_type,
            "criticality_level": self.criticality_level,
            "max_depth": self.max_depth,
            "max_subagents": self.max_subagents,
            "max_retries": self.max_retries,
            "max_tokens_or_compute_units": self.max_tokens_or_compute_units,
            "expires_at": self.expires_at,
            "validator_required": int(self.validator_required),
            "promotion_target": self.promotion_target,
            "allowed_tools": json.dumps(self.allowed_tools),
            "allowed_data_sources": json.dumps(self.allowed_data_sources),
            "maintenance_ticket_id": self.maintenance_ticket_id,
        }


@dataclass
class RootBudgetEnvelope:
    """
    Authoritative root budget envelope.
    Tied to a root task. Children may reduce, never expand.
    """
    root_budget_envelope_id: str
    task_id: str
    max_total_tokens_or_compute_units: int
    max_total_subagents: int
    max_total_wallclock: int        # seconds
    max_total_external_calls: int
    created_at: str

    def as_dict(self) -> dict:
        return {
            "root_budget_envelope_id": self.root_budget_envelope_id,
            "task_id": self.task_id,
            "max_total_tokens_or_compute_units": self.max_total_tokens_or_compute_units,
            "max_total_subagents": self.max_total_subagents,
            "max_total_wallclock": self.max_total_wallclock,
            "max_total_external_calls": self.max_total_external_calls,
            "created_at": self.created_at,
        }
