"""
Run repository — EPHEMERAL partition.

Heartbeat and zombie/stale detection live here.

Zombie definition (slice-1 narrow):
  - last heartbeat older than `stale_threshold_seconds`, OR
  - run.expires_at has passed without a terminal status
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from orchestrator.models.run import Run, RunHeartbeat


class RunRepository:

    DEFAULT_STALE_THRESHOLD_SECONDS = 300  # 5 minutes

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(self, run: Run) -> Run:
        self._conn.execute(
            """
            INSERT INTO runs (
                run_id, task_id, work_item_id, role, status,
                started_at, expires_at, attempt_no, parent_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id, run.task_id, run.work_item_id, run.role,
                run.status, run.started_at, run.expires_at,
                run.attempt_no, run.parent_run_id,
            ),
        )
        self._conn.commit()
        return run

    def get_run(self, run_id: str) -> Optional[Run]:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def update_status(self, run_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?", (status, run_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Heartbeats
    # ------------------------------------------------------------------

    def record_heartbeat(
        self,
        run_id: str,
        status: str,
        progress_note: Optional[str] = None,
    ) -> RunHeartbeat:
        hb = RunHeartbeat(
            heartbeat_id=str(uuid.uuid4()),
            run_id=run_id,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            status=status,
            progress_note=progress_note,
        )
        self._conn.execute(
            """
            INSERT INTO run_heartbeats (heartbeat_id, run_id, timestamp, status, progress_note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hb.heartbeat_id, hb.run_id, hb.timestamp, hb.status, hb.progress_note),
        )
        self._conn.commit()
        return hb

    def get_latest_heartbeat(self, run_id: str) -> Optional[RunHeartbeat]:
        row = self._conn.execute(
            """
            SELECT * FROM run_heartbeats
            WHERE run_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunHeartbeat(
            heartbeat_id=row["heartbeat_id"],
            run_id=row["run_id"],
            timestamp=row["timestamp"],
            status=row["status"],
            progress_note=row["progress_note"],
        )

    def list_heartbeats(self, run_id: str) -> list[RunHeartbeat]:
        rows = self._conn.execute(
            "SELECT * FROM run_heartbeats WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        ).fetchall()
        return [
            RunHeartbeat(
                heartbeat_id=r["heartbeat_id"],
                run_id=r["run_id"],
                timestamp=r["timestamp"],
                status=r["status"],
                progress_note=r["progress_note"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Zombie / stale / expiry detection
    # ------------------------------------------------------------------

    def is_promotable(
        self,
        run_id: str,
        stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    ) -> tuple[bool, str]:
        """
        Return (True, "") if the run may be used in a promotion.
        Return (False, reason) if it may not.

        A run is non-promotable if:
        1. It does not exist.
        2. Its status is not 'completed'.
        3. Its expires_at has passed (expired run).
        4. Its last heartbeat is older than stale_threshold_seconds (stale/zombie).
        5. There is no heartbeat at all.
        """
        run = self.get_run(run_id)
        if run is None:
            return False, f"Run '{run_id}' not found."

        now = datetime.now(tz=timezone.utc)

        # Expiry check
        try:
            expiry = datetime.fromisoformat(run.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False, f"Run '{run_id}' has invalid expires_at: {run.expires_at!r}"

        if now >= expiry:
            return False, f"Run '{run_id}' is expired (expires_at={run.expires_at})."

        # Status check
        if run.status != "completed":
            return False, (
                f"Run '{run_id}' status is '{run.status}'; "
                "only 'completed' runs may be promoted."
            )

        # Heartbeat staleness check
        latest_hb = self.get_latest_heartbeat(run_id)
        if latest_hb is None:
            return False, f"Run '{run_id}' has no heartbeats; cannot verify liveness."

        try:
            hb_time = datetime.fromisoformat(latest_hb.timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False, f"Run '{run_id}' has unparseable heartbeat timestamp."

        age = now - hb_time
        threshold = timedelta(seconds=stale_threshold_seconds)
        if age > threshold:
            return False, (
                f"Run '{run_id}' last heartbeat is {age.total_seconds():.0f}s old "
                f"(threshold={stale_threshold_seconds}s); run is stale/zombie."
            )

        return True, ""

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> Run:
        return Run(
            run_id=row["run_id"],
            task_id=row["task_id"],
            work_item_id=row["work_item_id"],
            role=row["role"],
            status=row["status"],
            started_at=row["started_at"],
            expires_at=row["expires_at"],
            attempt_no=row["attempt_no"],
            parent_run_id=row["parent_run_id"],
        )
