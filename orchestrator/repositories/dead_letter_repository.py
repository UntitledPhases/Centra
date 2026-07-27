"""
Dead-letter repository — EPHEMERAL partition.

failure_class and reason are required (NOT NULL at DB level and validated here).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.models.dead_letter import DeadLetterEntry


class DeadLetterRepository:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_entry(self, entry: DeadLetterEntry) -> DeadLetterEntry:
        if not entry.failure_class or not entry.failure_class.strip():
            raise ValueError("dead_letter_entry.failure_class is required and cannot be empty.")
        if not entry.reason or not entry.reason.strip():
            raise ValueError("dead_letter_entry.reason is required and cannot be empty.")

        self._conn.execute(
            """
            INSERT INTO dead_letter_entries (
                dead_letter_id, task_id, run_id,
                failure_class, reason, retry_count, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.dead_letter_id,
                entry.task_id,
                entry.run_id,
                entry.failure_class,
                entry.reason,
                entry.retry_count,
                entry.timestamp,
            ),
        )
        self._conn.commit()
        return entry

    def get_entry(self, dead_letter_id: str) -> Optional[DeadLetterEntry]:
        row = self._conn.execute(
            "SELECT * FROM dead_letter_entries WHERE dead_letter_id = ?",
            (dead_letter_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def list_for_task(self, task_id: str) -> list[DeadLetterEntry]:
        rows = self._conn.execute(
            "SELECT * FROM dead_letter_entries WHERE task_id = ? ORDER BY timestamp ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> DeadLetterEntry:
        return DeadLetterEntry(
            dead_letter_id=row["dead_letter_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            failure_class=row["failure_class"],
            reason=row["reason"],
            retry_count=row["retry_count"],
            timestamp=row["timestamp"],
        )
