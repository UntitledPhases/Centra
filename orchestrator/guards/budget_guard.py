"""
Budget guard: validates budget headers and enforces child-cannot-expand rule.

Rules enforced here:
1. Root budget must have all required fields with positive values.
2. Child budget may reduce but never expand any dimension vs. parent.
3. Expired budget (expires_at in the past) blocks validation.
4. check_budget_consumption is a stub for future accounting integration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from orchestrator.models.budget import BudgetHeader, RootBudgetEnvelope, REQUIRED_BUDGET_FIELDS


class BudgetViolationError(Exception):
    """Raised when a budget rule is violated."""


# Fields that a child budget must not exceed vs. its parent.
_COMPARABLE_BUDGET_DIMS = (
    "max_depth",
    "max_subagents",
    "max_retries",
    "max_tokens_or_compute_units",
)

_ROOT_ENVELOPE_DIMS = (
    "max_total_tokens_or_compute_units",
    "max_total_subagents",
    "max_total_wallclock",
    "max_total_external_calls",
)


def validate_root_budget(root_budget: RootBudgetEnvelope) -> None:
    """
    Validate the root budget envelope.
    All fields must be present and positive.
    """
    for dim in _ROOT_ENVELOPE_DIMS:
        val = getattr(root_budget, dim, None)
        if val is None:
            raise BudgetViolationError(f"Root budget missing required field: {dim}")
        if not isinstance(val, int) or val <= 0:
            raise BudgetViolationError(
                f"Root budget field '{dim}' must be a positive integer; got {val!r}"
            )


def validate_task_budget_header(header: BudgetHeader) -> None:
    """
    Validate that a task budget header contains all required fields.
    Also checks that expires_at has not already passed.
    """
    # Check field presence on the model (dataclass guarantees fields exist,
    # but check for sentinel None where a value is required).
    required_non_null = (
        "task_id", "task_type", "criticality_level", "promotion_target",
        "expires_at", "allowed_tools", "allowed_data_sources",
    )
    for field_name in required_non_null:
        val = getattr(header, field_name, None)
        if val is None or val == "":
            raise BudgetViolationError(
                f"Task budget header missing required field: {field_name}"
            )

    for dim in _COMPARABLE_BUDGET_DIMS:
        val = getattr(header, dim, None)
        if val is None:
            raise BudgetViolationError(f"Task budget header missing field: {dim}")
        if not isinstance(val, int) or val < 0:
            raise BudgetViolationError(
                f"Task budget field '{dim}' must be a non-negative integer; got {val!r}"
            )

    _assert_not_expired(header.expires_at, context="task budget header")


def validate_child_budget(parent: BudgetHeader, child: BudgetHeader) -> None:
    """
    Ensure child budget does not expand any dimension beyond parent.
    Also validates the child header itself.
    """
    validate_task_budget_header(child)

    for dim in _COMPARABLE_BUDGET_DIMS:
        parent_val = getattr(parent, dim)
        child_val  = getattr(child, dim)
        if child_val > parent_val:
            raise BudgetViolationError(
                f"Child budget expansion detected on '{dim}': "
                f"parent={parent_val} < child={child_val}. "
                "Children may reduce budget but never expand it."
            )


def check_budget_consumption(task_id: str, event: dict[str, Any]) -> None:
    """
    Stub: record or check a budget consumption event for a task.
    Full accounting integration is deferred to a later slice.

    In slice-1 this is intentionally minimal: it validates that the event
    carries a task_id and event_type, and does nothing else.
    A future implementation will compare cumulative consumption against
    the root_budget_envelope limits stored in the DB.

    TODO(slice-2): query root_budget_envelopes and sum consumption events
    to enforce max_total_tokens_or_compute_units / max_total_subagents etc.
    """
    if not task_id:
        raise BudgetViolationError("check_budget_consumption: task_id is required")
    if "event_type" not in event:
        raise BudgetViolationError("check_budget_consumption: event must include 'event_type'")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _assert_not_expired(expires_at: str, context: str = "") -> None:
    """Raise BudgetViolationError if the given ISO-8601 UTC timestamp is in the past."""
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise BudgetViolationError(
            f"Invalid expires_at format in {context}: {expires_at!r}"
        ) from exc

    now = datetime.now(tz=timezone.utc)
    if expiry <= now:
        raise BudgetViolationError(
            f"Budget is expired in {context}: expires_at={expires_at} now={now.isoformat()}"
        )
