"""
Validator repository — EPHEMERAL partition.

Writes validator_results. Read by promoter before any durable write.
Executor must not receive validator histories by default (context-loading rule preserved).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.models.validator import ValidatorResult, ValidationStatus


class ValidatorRepository:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_result(self, result: ValidatorResult) -> ValidatorResult:
        self._conn.execute(
            """
            INSERT INTO validator_results (
                validator_result_id, task_id, run_id, validation_status,
                confidence_score, failed_constraints, grounding_status,
                schema_status, policy_status, remediation_action, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.validator_result_id,
                result.task_id,
                result.run_id,
                result.validation_status,
                result.confidence_score,
                json.dumps(result.failed_constraints),
                result.grounding_status,
                result.schema_status,
                result.policy_status,
                result.remediation_action,
                result.notes,
                result.created_at,
            ),
        )
        self._conn.commit()
        return result

    def get_result(self, validator_result_id: str) -> Optional[ValidatorResult]:
        row = self._conn.execute(
            "SELECT * FROM validator_results WHERE validator_result_id = ?",
            (validator_result_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_result(row)

    def get_latest_for_task(self, task_id: str) -> Optional[ValidatorResult]:
        row = self._conn.execute(
            """
            SELECT * FROM validator_results
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_result(row)

    # ------------------------------------------------------------------
    # Context-loading boundary preservation
    # Executor must NOT call get_history_for_executor — this method does not exist.
    # If needed in future: route via a role-scoped query that strips validator details.
    # TODO(slice-2): implement role-scoped context loading per spec section 7.
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> ValidatorResult:
        return ValidatorResult(
            validator_result_id=row["validator_result_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            validation_status=row["validation_status"],
            confidence_score=row["confidence_score"],
            failed_constraints=json.loads(row["failed_constraints"] or "[]"),
            grounding_status=row["grounding_status"],
            schema_status=row["schema_status"],
            policy_status=row["policy_status"],
            remediation_action=row["remediation_action"],
            notes=row["notes"],
            created_at=row["created_at"],
        )
