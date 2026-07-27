"""
RepoContext: bundled repository references for a single DB connection.

Passed as a single argument through the controller → workflow → runners chain.
Avoids threading 8+ separate repo arguments everywhere while keeping the
repos explicit (not hidden in a service locator).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from orchestrator.stores.artifact_store import ArtifactStore
from orchestrator.repositories.task_repository import TaskRepository
from orchestrator.repositories.run_repository import RunRepository
from orchestrator.repositories.proposal_repository import ProposalRepository
from orchestrator.repositories.validator_repository import ValidatorRepository
from orchestrator.repositories.promotion_repository import PromotionRepository
from orchestrator.repositories.durable_repository import DurableRepository
from orchestrator.repositories.dead_letter_repository import DeadLetterRepository


@dataclass
class RepoContext:
    """
    All repositories wired together for one DB connection.
    The controller and workflow do not call raw SQL — they use these repos.
    """
    conn: sqlite3.Connection
    task_repo: TaskRepository
    run_repo: RunRepository
    proposal_repo: ProposalRepository
    validator_repo: ValidatorRepository
    promotion_repo: PromotionRepository
    durable_repo: DurableRepository
    dead_letter_repo: DeadLetterRepository
    artifact_store: ArtifactStore

    @classmethod
    def from_connection(
        cls,
        conn: sqlite3.Connection,
        artifact_store: ArtifactStore,
    ) -> "RepoContext":
        """Convenience constructor: wire all repos from a single connection."""
        run_repo = RunRepository(conn)
        validator_repo = ValidatorRepository(conn)
        promotion_repo = PromotionRepository(conn, validator_repo, run_repo)
        proposal_repo = ProposalRepository(conn, artifact_store)
        durable_repo = DurableRepository(conn, promotion_repo, proposal_repo, artifact_store)
        return cls(
            conn=conn,
            task_repo=TaskRepository(conn),
            run_repo=run_repo,
            proposal_repo=proposal_repo,
            validator_repo=validator_repo,
            promotion_repo=promotion_repo,
            durable_repo=durable_repo,
            dead_letter_repo=DeadLetterRepository(conn),
            artifact_store=artifact_store,
        )
