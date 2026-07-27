"""
Tests 7-9: Budget guard enforcement.

7. Task creation without full budget header fails.
8. Child budget expansion fails.
9. Expired budget fails validation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.guards.budget_guard import (
    BudgetViolationError,
    validate_task_budget_header,
    validate_child_budget,
    validate_root_budget,
    check_budget_consumption,
)
from orchestrator.models.budget import BudgetHeader, RootBudgetEnvelope
from orchestrator.tests.conftest import make_budget_header, make_root_envelope, future_ts, past_ts


class TestTaskCreationWithoutBudget:
    """Test 7: task creation fails if budget fields are missing."""

    def test_task_creation_without_expires_at_fails(self, task_repo):
        import dataclasses
        header = make_budget_header()
        # Corrupt the expires_at field
        bad_header = dataclasses.replace(header, expires_at="")
        with pytest.raises(BudgetViolationError, match="expires_at"):
            task_repo.create_task(bad_header)

    def test_task_creation_without_task_type_fails(self, task_repo):
        import dataclasses
        header = make_budget_header()
        bad_header = dataclasses.replace(header, task_type="")
        with pytest.raises(BudgetViolationError, match="task_type"):
            task_repo.create_task(bad_header)

    def test_task_creation_without_allowed_tools_fails(self, task_repo):
        import dataclasses
        header = make_budget_header()
        bad_header = dataclasses.replace(header, allowed_tools=None)
        with pytest.raises(BudgetViolationError, match="allowed_tools"):
            task_repo.create_task(bad_header)

    def test_task_creation_with_negative_max_tokens_fails(self, task_repo):
        import dataclasses
        header = make_budget_header()
        bad_header = dataclasses.replace(header, max_tokens_or_compute_units=-1)
        with pytest.raises(BudgetViolationError, match="max_tokens_or_compute_units"):
            task_repo.create_task(bad_header)

    def test_task_creation_with_valid_budget_succeeds(self, task_repo):
        header = make_budget_header()
        task = task_repo.create_task(header)
        assert task.task_id == header.task_id


class TestChildBudgetExpansionBlocked:
    """Test 8: child budget must not exceed parent on any dimension."""

    def test_child_max_tokens_exceeds_parent_fails(self):
        parent = make_budget_header(max_tokens=1000)
        child = make_budget_header(
            parent_task_id=parent.task_id, max_tokens=2000  # expansion!
        )
        with pytest.raises(BudgetViolationError, match="max_tokens_or_compute_units"):
            validate_child_budget(parent, child)

    def test_child_max_subagents_exceeds_parent_fails(self):
        parent = make_budget_header(max_subagents=2)
        child = make_budget_header(parent_task_id=parent.task_id, max_subagents=5)
        with pytest.raises(BudgetViolationError, match="max_subagents"):
            validate_child_budget(parent, child)

    def test_child_max_depth_exceeds_parent_fails(self):
        parent = make_budget_header(max_depth=2)
        child = make_budget_header(parent_task_id=parent.task_id, max_depth=3)
        with pytest.raises(BudgetViolationError, match="max_depth"):
            validate_child_budget(parent, child)

    def test_child_max_retries_exceeds_parent_fails(self):
        parent = make_budget_header(max_retries=1)
        child = make_budget_header(parent_task_id=parent.task_id, max_retries=3)
        with pytest.raises(BudgetViolationError, match="max_retries"):
            validate_child_budget(parent, child)

    def test_child_equal_to_parent_is_allowed(self):
        parent = make_budget_header(max_tokens=1000, max_subagents=4)
        child = make_budget_header(
            parent_task_id=parent.task_id, max_tokens=1000, max_subagents=4
        )
        # Must not raise
        validate_child_budget(parent, child)

    def test_child_reduced_from_parent_is_allowed(self):
        parent = make_budget_header(max_tokens=1000, max_depth=5)
        child = make_budget_header(
            parent_task_id=parent.task_id, max_tokens=500, max_depth=2
        )
        validate_child_budget(parent, child)


class TestExpiredBudget:
    """Test 9: expired budget fails validation."""

    def test_expired_expires_at_fails(self):
        expired_header = make_budget_header(expires_at=past_ts(120))
        with pytest.raises(BudgetViolationError, match="expired"):
            validate_task_budget_header(expired_header)

    def test_future_expires_at_passes(self):
        header = make_budget_header(expires_at=future_ts(3600))
        # Must not raise
        validate_task_budget_header(header)

    def test_invalid_expires_at_format_fails(self):
        import dataclasses
        header = make_budget_header()
        bad = dataclasses.replace(header, expires_at="not-a-date")
        with pytest.raises(BudgetViolationError, match="Invalid"):
            validate_task_budget_header(bad)

    def test_root_envelope_missing_field_fails(self):
        import dataclasses
        env = make_root_envelope()
        bad = dataclasses.replace(env, max_total_subagents=0)
        with pytest.raises(BudgetViolationError, match="max_total_subagents"):
            validate_root_budget(bad)

    def test_root_envelope_valid_passes(self):
        env = make_root_envelope()
        validate_root_budget(env)  # Must not raise


class TestCheckBudgetConsumption:
    """Stub behavior for check_budget_consumption."""

    def test_requires_task_id(self):
        with pytest.raises(BudgetViolationError, match="task_id"):
            check_budget_consumption("", {"event_type": "token_used"})

    def test_requires_event_type(self):
        with pytest.raises(BudgetViolationError, match="event_type"):
            check_budget_consumption("task-123", {"amount": 5})

    def test_valid_call_does_not_raise(self):
        check_budget_consumption("task-123", {"event_type": "token_used", "amount": 10})
