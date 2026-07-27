"""
Durable repository — DURABLE partition.

This is the ONLY path that may write approved_artifacts, validated_observations,
and accepted_run_summaries.

Enforcement:
1. Every write method requires a promotion_record_id.
2. The promotion_record is verified to exist before writing.
3. Artifact hash is verified against the artifact store before promotion.
4. No generic direct durable insert helpers are exposed.

Role enforcement: callers must pass role='promoter'.
The partition_guard.assert_durable_write_is_promoter() is called at entry.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.guards.partition_guard import assert_durable_write_is_promoter
from orchestrator.models.artifact import ApprovedArtifact
from orchestrator.models.promotion import ValidatedObservation, AcceptedRunSummary
from orchestrator.repositories.promotion_repository import PromotionRepository
from orchestrator.repositories.proposal_repository import ProposalRepository
from orchestrator.stores.artifact_store import ArtifactStore, ArtifactIntegrityError


class DurableWriteError(Exception):
    """Raised when a durable write is blocked due to missing or invalid linkage."""


class DurableRepository:

    def __init__(
        self,
        conn: sqlite3.Connection,
        promotion_repo: PromotionRepository,
        proposal_repo: ProposalRepository,
        artifact_store: ArtifactStore,
    ) -> None:
        self._conn = conn
        self._promotion_repo = promotion_repo
        self._proposal_repo = proposal_repo
        self._store = artifact_store

    # ------------------------------------------------------------------
    # Approved artifacts
    # ------------------------------------------------------------------

    def promote_artifact(
        self,
        role: str,
        approved_artifact_id: str,
        source_artifact_id: str,
        promotion_record_id: str,
    ) -> ApprovedArtifact:
        """
        Promote a proposed artifact to the durable layer.

        Checks:
        1. role must be 'promoter'.
        2. promotion_record must exist (DB FK also enforces this).
        3. source artifact must exist and its hash must verify against the store.
        """
        assert_durable_write_is_promoter(role)
        self._assert_promotion_record_exists(promotion_record_id)

        source = self._proposal_repo.get_proposed_artifact(source_artifact_id)
        if source is None:
            raise DurableWriteError(
                f"Source artifact '{source_artifact_id}' not found in proposal layer."
            )

        # Artifact hash integrity check before promotion
        if not self._store.verify(source.content_hash, source.storage_uri):
            raise ArtifactIntegrityError(
                f"Artifact integrity check failed for '{source_artifact_id}'. "
                "Stored hash does not match content. Promotion blocked."
            )

        now = datetime.now(tz=timezone.utc).isoformat()
        approved = ApprovedArtifact(
            approved_artifact_id=approved_artifact_id,
            source_artifact_id=source_artifact_id,
            promotion_record_id=promotion_record_id,
            content_hash=source.content_hash,
            storage_uri=source.storage_uri,
            created_at=now,
        )

        self._conn.execute(
            """
            INSERT INTO approved_artifacts (
                approved_artifact_id, source_artifact_id, promotion_record_id,
                content_hash, storage_uri, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                approved.approved_artifact_id,
                approved.source_artifact_id,
                approved.promotion_record_id,
                approved.content_hash,
                approved.storage_uri,
                approved.created_at,
            ),
        )
        self._conn.commit()
        return approved

    def get_approved_artifact(self, approved_artifact_id: str) -> Optional[ApprovedArtifact]:
        row = self._conn.execute(
            "SELECT * FROM approved_artifacts WHERE approved_artifact_id = ?",
            (approved_artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovedArtifact(
            approved_artifact_id=row["approved_artifact_id"],
            source_artifact_id=row["source_artifact_id"],
            promotion_record_id=row["promotion_record_id"],
            content_hash=row["content_hash"],
            storage_uri=row["storage_uri"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Validated observations
    # ------------------------------------------------------------------

    def promote_observation(
        self,
        role: str,
        validated_observation_id: str,
        source_observation_id: str,
        promotion_record_id: str,
        content_hash: str,
    ) -> ValidatedObservation:
        assert_durable_write_is_promoter(role)
        self._assert_promotion_record_exists(promotion_record_id)

        now = datetime.now(tz=timezone.utc).isoformat()
        obs = ValidatedObservation(
            validated_observation_id=validated_observation_id,
            source_observation_id=source_observation_id,
            promotion_record_id=promotion_record_id,
            content_hash=content_hash,
            created_at=now,
        )
        self._conn.execute(
            """
            INSERT INTO validated_observations (
                validated_observation_id, source_observation_id,
                promotion_record_id, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                obs.validated_observation_id,
                obs.source_observation_id,
                obs.promotion_record_id,
                obs.content_hash,
                obs.created_at,
            ),
        )
        self._conn.commit()
        return obs

    # ------------------------------------------------------------------
    # Accepted run summaries
    # ------------------------------------------------------------------

    def promote_run_summary(
        self,
        role: str,
        run_summary_id: str,
        task_id: str,
        promotion_record_id: str,
        summary_artifact_id: str,
    ) -> AcceptedRunSummary:
        assert_durable_write_is_promoter(role)
        self._assert_promotion_record_exists(promotion_record_id)

        now = datetime.now(tz=timezone.utc).isoformat()
        summary = AcceptedRunSummary(
            run_summary_id=run_summary_id,
            task_id=task_id,
            promotion_record_id=promotion_record_id,
            summary_artifact_id=summary_artifact_id,
            created_at=now,
        )
        self._conn.execute(
            """
            INSERT INTO accepted_run_summaries (
                run_summary_id, task_id, promotion_record_id,
                summary_artifact_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                summary.run_summary_id,
                summary.task_id,
                summary.promotion_record_id,
                summary.summary_artifact_id,
                summary.created_at,
            ),
        )
        self._conn.commit()
        return summary

    # ------------------------------------------------------------------
    # Internal — no generic insert helpers exposed past this line
    # ------------------------------------------------------------------

    def _assert_promotion_record_exists(self, promotion_record_id: str) -> None:
        row = self._conn.execute(
            "SELECT promotion_record_id FROM promotion_records WHERE promotion_record_id = ?",
            (promotion_record_id,),
        ).fetchone()
        if row is None:
            raise DurableWriteError(
                f"Durable write blocked: promotion_record '{promotion_record_id}' does not exist. "
                "All durable writes require a linked promotion record."
            )
