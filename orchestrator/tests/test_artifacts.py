"""
Tests 10-11: Artifact integrity enforcement.

10. Artifact hash/store integrity works (round-trip).
11. Artifact hash mismatch is detected where relevant.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from orchestrator.stores.artifact_store import (
    ArtifactStore,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
)
from orchestrator.tests.conftest import make_budget_header, make_run, make_validator_result, make_promotion_record


class TestArtifactStoreIntegrity:
    """Test 10: hash-bound storage works correctly."""

    def test_put_and_get_round_trip(self, artifact_store):
        content = b"the quick brown fox"
        digest, uri = artifact_store.put(content)
        retrieved = artifact_store.get(digest, uri)
        assert retrieved == content

    def test_hash_is_sha256(self, artifact_store):
        content = b"deterministic"
        digest, _ = artifact_store.put(content)
        expected = hashlib.sha256(content).hexdigest()
        assert digest == expected

    def test_put_is_idempotent(self, artifact_store):
        content = b"same bytes"
        d1, u1 = artifact_store.put(content)
        d2, u2 = artifact_store.put(content)
        assert d1 == d2 and u1 == u2

    def test_put_text(self, artifact_store):
        text = "hello world"
        digest, uri = artifact_store.put_text(text)
        content = artifact_store.get(digest, uri)
        assert content.decode() == text

    def test_put_json(self, artifact_store):
        obj = {"key": "value", "num": 42}
        digest, uri = artifact_store.put_json(obj)
        content = artifact_store.get(digest, uri)
        import json
        assert json.loads(content) == obj

    def test_verify_returns_true_for_valid(self, artifact_store):
        content = b"valid content"
        digest, uri = artifact_store.put(content)
        assert artifact_store.verify(digest, uri) is True

    def test_exists_returns_true_after_put(self, artifact_store):
        content = b"exists check"
        digest, _ = artifact_store.put(content)
        assert artifact_store.exists(digest) is True

    def test_not_found_raises(self, artifact_store):
        with pytest.raises(ArtifactNotFoundError):
            artifact_store.get("a" * 64)  # plausible but non-existent hash


class TestArtifactHashMismatch:
    """Test 11: mismatch is detected on retrieval and at promotion time."""

    def test_corrupted_file_raises_integrity_error(self, artifact_store):
        content = b"original content"
        digest, uri = artifact_store.put(content)

        # Tamper with the stored file directly
        from pathlib import Path
        Path(uri).write_bytes(b"tampered content")

        with pytest.raises(ArtifactIntegrityError):
            artifact_store.get(digest, uri)

    def test_verify_returns_false_for_tampered(self, artifact_store):
        content = b"to be tampered"
        digest, uri = artifact_store.put(content)
        from pathlib import Path
        Path(uri).write_bytes(b"bad data")
        assert artifact_store.verify(digest, uri) is False

    def test_promotion_blocked_on_hash_mismatch(
        self, conn, task_repo, run_repo, proposal_repo,
        validator_repo, promotion_repo, durable_repo, artifact_store
    ):
        """
        If the stored artifact bytes have been tampered with between proposal and
        promotion, durable_repo.promote_artifact must detect it and block.
        """
        header = make_budget_header()
        task = task_repo.create_task(header)

        content = b"artifact to tamper"
        artifact = proposal_repo.create_proposed_artifact(
            artifact_id=str(uuid.uuid4()),
            task_id=task.task_id,
            artifact_type="result",
            content=content,
        )

        # Tamper after proposal write
        from pathlib import Path
        Path(artifact.storage_uri).write_bytes(b"tampered after proposal")

        # Set up a valid promotion path
        executor_run = make_run(conn, task.task_id, role="executor", status="completed")
        run_repo.record_heartbeat(executor_run.run_id, "completed")
        validator_run = make_run(conn, task.task_id, role="validator", status="completed")
        vr = make_validator_result(conn, task.task_id, validator_run.run_id, status="PASS")
        pr = make_promotion_record(
            conn, task.task_id, vr.validator_result_id, source_artifact_id=artifact.artifact_id
        )

        with pytest.raises(ArtifactIntegrityError):
            durable_repo.promote_artifact(
                role="promoter",
                approved_artifact_id=str(uuid.uuid4()),
                source_artifact_id=artifact.artifact_id,
                promotion_record_id=pr.promotion_record_id,
            )

    def test_proposal_repo_fetch_detects_tampered_content(
        self, conn, task_repo, proposal_repo
    ):
        """Fetching content from ProposalRepository re-verifies hash."""
        header = make_budget_header()
        task = task_repo.create_task(header)

        artifact = proposal_repo.create_proposed_artifact(
            artifact_id=str(uuid.uuid4()),
            task_id=task.task_id,
            artifact_type="result",
            content=b"clean content",
        )

        from pathlib import Path
        Path(artifact.storage_uri).write_bytes(b"dirty content")

        with pytest.raises(ArtifactIntegrityError):
            proposal_repo.get_proposed_artifact_content(artifact.artifact_id)
