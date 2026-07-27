"""Artifact models (proposed and approved)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProposedArtifact:
    artifact_id: str
    task_id: str
    run_id: Optional[str]
    artifact_type: str
    content_hash: str
    storage_uri: str
    schema_valid: bool
    created_at: str


@dataclass
class ApprovedArtifact:
    approved_artifact_id: str
    source_artifact_id: str
    promotion_record_id: str    # NOT NULL — enforced at DB and repo level
    content_hash: str
    storage_uri: str
    created_at: str
