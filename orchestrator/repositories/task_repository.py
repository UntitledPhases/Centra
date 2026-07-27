"""
Task repository — PROPOSAL partition.

Responsibilities:
- Create tasks with mandatory full budget headers (fails if any required field missing).
- Read tasks by id or status.
- Update task status.
- Create root_budget_envelopes (root task only).

Does NOT write durable rows. Does NOT expose generic durable inserts.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.guards.budget_guard import validate_task_budget_header, validate_root_budget
from orchestrator.models.budget import BudgetHeader, RootBudgetEnvelope
from orchestrator.models.task import Task, WorkItem


class MissingBudgetFieldError(Exception):
    """Raised when a task is created without a full budget header."""


class TaskRepository:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def create_task(self, header: BudgetHeader) -> Task:
        """
        Create a task row from a full BudgetHeader.
        Fails if any required budget field is missing or budget is expired.
        """
        validate_task_budget_header(header)   # raises BudgetViolationError if invalid

        now = datetime.now(tz=timezone.utc).isoformat()
        row = header.as_dict()
        row["status"] = "pending"
        row["created_at"] = now

        self._conn.execute(
            """
            INSERT INTO tasks (
                task_id, parent_task_id, task_type, criticality_level,
                status, promotion_target,
                max_depth, max_subagents, max_retries, max_tokens_or_compute_units,
                validator_required, allowed_tools, allowed_data_sources,
                maintenance_ticket_id, created_at, expires_at
            ) VALUES (
                :task_id, :parent_task_id, :task_type, :criticality_level,
                :status, :promotion_target,
                :max_depth, :max_subagents, :max_retries, :max_tokens_or_compute_units,
                :validator_required, :allowed_tools, :allowed_data_sources,
                :maintenance_ticket_id, :created_at, :expires_at
            )
            """,
            row,
        )
        self._conn.commit()
        return self.get_task(header.task_id)

    def get_task(self, task_id: str) -> Optional[Task]:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def update_status(self, task_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id)
        )
        self._conn.commit()

    def list_by_status(self, status: str) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status = ?", (status,)
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    # ------------------------------------------------------------------
    # Root budget envelopes
    # ------------------------------------------------------------------

    def create_root_budget_envelope(self, envelope: RootBudgetEnvelope) -> RootBudgetEnvelope:
        """
        Persist the authoritative root budget envelope.
        Validates envelope fields before writing.
        """
        validate_root_budget(envelope)
        self._conn.execute(
            """
            INSERT INTO root_budget_envelopes (
                root_budget_envelope_id, task_id,
                max_total_tokens_or_compute_units, max_total_subagents,
                max_total_wallclock, max_total_external_calls, created_at
            ) VALUES (
                :root_budget_envelope_id, :task_id,
                :max_total_tokens_or_compute_units, :max_total_subagents,
                :max_total_wallclock, :max_total_external_calls, :created_at
            )
            """,
            envelope.as_dict(),
        )
        self._conn.commit()
        return envelope

    def get_root_budget_envelope(self, task_id: str) -> Optional[RootBudgetEnvelope]:
        row = self._conn.execute(
            "SELECT * FROM root_budget_envelopes WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return RootBudgetEnvelope(
            root_budget_envelope_id=row["root_budget_envelope_id"],
            task_id=row["task_id"],
            max_total_tokens_or_compute_units=row["max_total_tokens_or_compute_units"],
            max_total_subagents=row["max_total_subagents"],
            max_total_wallclock=row["max_total_wallclock"],
            max_total_external_calls=row["max_total_external_calls"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Work items
    # ------------------------------------------------------------------

    def create_work_item(self, item: WorkItem) -> WorkItem:
        self._conn.execute(
            """
            INSERT INTO work_items (
                work_item_id, task_id, assigned_role, instructions,
                input_artifact_refs, output_schema_ref, attempt_no, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.work_item_id, item.task_id, item.assigned_role,
                item.instructions,
                json.dumps(item.input_artifact_refs),
                item.output_schema_ref,
                item.attempt_no,
                item.created_at,
            ),
        )
        self._conn.commit()
        return item

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            task_id=row["task_id"],
            parent_task_id=row["parent_task_id"],
            task_type=row["task_type"],
            criticality_level=row["criticality_level"],
            status=row["status"],
            promotion_target=row["promotion_target"],
            max_depth=row["max_depth"],
            max_subagents=row["max_subagents"],
            max_retries=row["max_retries"],
            max_tokens_or_compute_units=row["max_tokens_or_compute_units"],
            validator_required=bool(row["validator_required"]),
            allowed_tools=json.loads(row["allowed_tools"]),
            allowed_data_sources=json.loads(row["allowed_data_sources"]),
            maintenance_ticket_id=row["maintenance_ticket_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )
