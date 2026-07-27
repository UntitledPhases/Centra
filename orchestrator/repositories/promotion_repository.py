"""
Promotion repository — EPHEMERAL partition (promotion_records).

This is the gate between proposal and durable.

Enforcement:
1. promotion_record must reference an existing validator_result.
2. validator_result.validation_status must be PASS.
3. FAIL and ESCALATE are unconditionally blocked — executor self-check is advisory only.
4. Deterministic invalid state (bad status string) also blocks.
5. Stale/zombie/expired runs are blocked via RunRepository.is_promotable().
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.models.promotion import PromotionRecord
from orchestrator.models.validator import ValidationStatus
from orchestrator.repositories.validator_repository import ValidatorRepository
from orchestrator.repositories.run_repository import RunRepository


class PromotionBlockedError(Exception):
    """Raised when a promotion is blocked by a guard."""


class PromotionRepository:

    def __init__(
        self,
        conn: sqlite3.Connection,
        validator_repo: ValidatorRepository,
        run_repo: RunRepository,
    ) -> None:
        self._conn = conn
        self._validator_repo = validator_repo
        self._run_repo = run_repo

    def create_promotion_record(
        self,
        record: PromotionRecord,
        executor_run_id: Optional[str] = None,
        stale_threshold_seconds: int = RunRepository.DEFAULT_STALE_THRESHOLD_SECONDS,
    ) -> PromotionRecord:
        """
        Create a promotion record after passing all guards.

        Guards (in order):
        1. validator_result must exist.
        2. validation_status must be PASS (deterministic rule outranks confidence text).
        3. executor run must be promotable (not stale/expired/zombie).

        executor_run_id is the run whose output is being promoted. If provided,
        its liveness is checked. Passing None skips liveness check (use only for
        non-executor promotions, e.g., obs-only or summary promotions where the
        run is already recorded in the promotion record).
        """
        # Guard 1: validator_result linkage
        vr = self._validator_repo.get_result(record.validation_result_id)
        if vr is None:
            raise PromotionBlockedError(
                f"Promotion blocked: validator_result '{record.validation_result_id}' "
                "not found. A promotion record requires a linked validator result."
            )

        # Guard 2: PASS-only promotion
        if not ValidationStatus.is_promotable(vr.validation_status):
            raise PromotionBlockedError(
                f"Promotion blocked: validator_result status is '{vr.validation_status}'. "
                "Durable promotion requires PASS. FAIL and ESCALATE are unconditionally "
                "blocked regardless of confidence score."
            )

        # Guard 3: executor run liveness (if supplied)
        if executor_run_id is not None:
            ok, reason = self._run_repo.is_promotable(
                executor_run_id, stale_threshold_seconds
            )
            if not ok:
                raise PromotionBlockedError(
                    f"Promotion blocked: executor run '{executor_run_id}' is "
                    f"non-promotable. Reason: {reason}"
                )

        self._conn.execute(
            """
            INSERT INTO promotion_records (
                promotion_record_id, task_id, source_layer, target_layer,
                source_artifact_id, target_object_id,
                executor_id, validator_id, validation_result_id,
                approval_metadata, artifact_input_hash, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.promotion_record_id,
                record.task_id,
                record.source_layer,
                record.target_layer,
                record.source_artifact_id,
                record.target_object_id,
                record.executor_id,
                record.validator_id,
                record.validation_result_id,
                record.approval_metadata,
                record.artifact_input_hash,
                record.timestamp,
            ),
        )
        self._conn.commit()
        return record

    def get_promotion_record(self, promotion_record_id: str) -> Optional[PromotionRecord]:
        row = self._conn.execute(
            "SELECT * FROM promotion_records WHERE promotion_record_id = ?",
            (promotion_record_id,),
        ).fetchone()
        if row is None:
            return None
        return PromotionRecord(
            promotion_record_id=row["promotion_record_id"],
            task_id=row["task_id"],
            source_layer=row["source_layer"],
            target_layer=row["target_layer"],
            source_artifact_id=row["source_artifact_id"],
            target_object_id=row["target_object_id"],
            executor_id=row["executor_id"],
            validator_id=row["validator_id"],
            validation_result_id=row["validation_result_id"],
            approval_metadata=row["approval_metadata"],
            artifact_input_hash=row["artifact_input_hash"],
            timestamp=row["timestamp"],
        )
