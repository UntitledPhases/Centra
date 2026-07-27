"""
Artifact store: hash-bound, out-of-row content storage.

Artifacts are content-addressed by SHA-256.
Large content is stored on-disk; the DB row holds only the hash + URI.
Mismatch between stored hash and retrieved content raises ArtifactIntegrityError.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional


class ArtifactIntegrityError(Exception):
    """Raised when a stored artifact's hash does not match its content."""


class ArtifactNotFoundError(Exception):
    """Raised when a requested artifact does not exist in the store."""


class ArtifactStore:
    """
    File-system backed artifact store.
    Files are named by their SHA-256 hex digest.
    The DB row carries content_hash and storage_uri; this store owns the bytes.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(self, content: bytes) -> tuple[str, str]:
        """
        Store content and return (content_hash, storage_uri).
        Idempotent: writing the same bytes twice returns the same values.
        """
        digest = self._sha256(content)
        path = self._path_for(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return digest, str(path)

    def put_text(self, text: str, encoding: str = "utf-8") -> tuple[str, str]:
        return self.put(text.encode(encoding))

    def put_json(self, obj: object) -> tuple[str, str]:
        return self.put_text(json.dumps(obj, separators=(",", ":")))

    # ------------------------------------------------------------------
    # Read + verify
    # ------------------------------------------------------------------

    def get(self, content_hash: str, storage_uri: Optional[str] = None) -> bytes:
        """
        Retrieve content by hash. Verifies integrity on retrieval.
        Raises ArtifactNotFoundError if missing, ArtifactIntegrityError on mismatch.
        """
        path = self._resolve(content_hash, storage_uri)
        if not path.exists():
            raise ArtifactNotFoundError(
                f"Artifact not found: hash={content_hash} uri={storage_uri}"
            )
        content = path.read_bytes()
        actual = self._sha256(content)
        if actual != content_hash:
            raise ArtifactIntegrityError(
                f"Hash mismatch: expected={content_hash} actual={actual}"
            )
        return content

    def verify(self, content_hash: str, storage_uri: Optional[str] = None) -> bool:
        """
        Return True iff stored content matches the given hash.
        Does not raise; use for pre-promotion checks.
        """
        try:
            self.get(content_hash, storage_uri)
            return True
        except (ArtifactNotFoundError, ArtifactIntegrityError):
            return False

    def exists(self, content_hash: str) -> bool:
        return self._path_for(content_hash).exists()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _path_for(self, digest: str) -> Path:
        # Two-level directory sharding to avoid large flat directories.
        return self._base / digest[:2] / digest[2:]

    def _resolve(self, content_hash: str, storage_uri: Optional[str]) -> Path:
        if storage_uri:
            return Path(storage_uri)
        return self._path_for(content_hash)

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
