"""
Proposal repository — PROPOSAL partition.

Writes proposed_artifacts and proposed_observations.
Artifact content is stored out-of-row in the ArtifactStore.
Hash is verified on write (store guarantees it) and on fetch.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from orchestrator.models.artifact import ProposedArtifact
from orchestrator.stores.artifact_store import ArtifactStore, ArtifactIntegrityError


class ProposalRepository:

    def __init__(self, conn: sqlite3.Connection, artifact_store: ArtifactStore) -> None:
        self._conn = conn
        self._store = artifact_store

    # ------------------------------------------------------------------
    # Proposed artifacts
    # ------------------------------------------------------------------

    def create_proposed_artifact(
        self,
        artifact_id: str,
        task_id: str,
        artifact_type: str,
        content: bytes,
        run_id: Optional[str] = None,
        schema_valid: bool = False,
    ) -> ProposedArtifact:
        """
        Store content in the artifact store, then write the DB row.
        The content_hash is produced by the store (SHA-256).
        """
        content_hash, storage_uri = self._store.put(content)
        now = datetime.now(tz=timezone.utc).isoformat()

        artifact = ProposedArtifact(
            artifact_id=artifact_id,
            task_id=task_id,
            run_id=run_id,
            artifact_type=artifact_type,
            content_hash=content_hash,
            storage_uri=storage_uri,
            schema_valid=schema_valid,
            created_at=now,
        )

        self._conn.execute(
            """
            INSERT INTO proposed_artifacts (
                artifact_id, task_id, run_id, artifact_type,
                content_hash, storage_uri, schema_valid, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id, artifact.task_id, artifact.run_id,
                artifact.artifact_type, artifact.content_hash,
                artifact.storage_uri, int(artifact.schema_valid), artifact.created_at,
            ),
        )
        self._conn.commit()
        return artifact

    def get_proposed_artifact(self, artifact_id: str) -> Optional[ProposedArtifact]:
        row = self._conn.execute(
            "SELECT * FROM proposed_artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_artifact(row)

    def get_proposed_artifact_content(self, artifact_id: str) -> bytes:
        """
        Fetch artifact content from store, verifying hash integrity.
        Raises ArtifactIntegrityError on mismatch.
        """
        artifact = self.get_proposed_artifact(artifact_id)
        if artifact is None:
            raise FileNotFoundError(f"Proposed artifact not found: {artifact_id}")
        return self._store.get(artifact.content_hash, artifact.storage_uri)

    # ------------------------------------------------------------------
    # Proposed observations
    # ------------------------------------------------------------------

    def create_proposed_observation(
        self,
        observation_id: str,
        task_id: str,
        content_hash: str,
        artifact_id: Optional[str] = None,
    ) -> dict:
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO proposed_observations (
                observation_id, task_id, artifact_id, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (observation_id, task_id, artifact_id, content_hash, now),
        )
        self._conn.commit()
        return {
            "observation_id": observation_id,
            "task_id": task_id,
            "artifact_id": artifact_id,
            "content_hash": content_hash,
            "created_at": now,
        }

    def get_proposed_observation(self, observation_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM proposed_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> ProposedArtifact:
        return ProposedArtifact(
            artifact_id=row["artifact_id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            artifact_type=row["artifact_type"],
            content_hash=row["content_hash"],
            storage_uri=row["storage_uri"],
            schema_valid=bool(row["schema_valid"]),
            created_at=row["created_at"],
        )
