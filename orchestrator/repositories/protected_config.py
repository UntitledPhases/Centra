"""
Protected config access layer — READ-ONLY at runtime.

No write methods are exposed on this class.
Config is seeded by migrations or a one-time seed script, not by runtime code.
Attempting to import and call a write method that does not exist is a hard error.

Tables covered: mission, policy, approval_rules, authority_scope, trusted_registry.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


class ProtectedConfigMutationError(Exception):
    """Raised if runtime code attempts to mutate protected config."""


class ProtectedConfigRepository:
    """
    Read-only access to protected configuration tables.
    There are deliberately no insert/update/delete methods.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Mission
    # ------------------------------------------------------------------

    def get_mission(self, mission_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM mission WHERE mission_id = ?", (mission_id,)
        ).fetchone()

    def list_missions(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM mission").fetchall()

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def get_policy(self, policy_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM policy WHERE policy_id = ?", (policy_id,)
        ).fetchone()

    def list_policies(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM policy").fetchall()

    # ------------------------------------------------------------------
    # Approval rules
    # ------------------------------------------------------------------

    def get_approval_rules_for_layer(self, target_layer: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM approval_rules WHERE target_layer = ?", (target_layer,)
        ).fetchall()

    # ------------------------------------------------------------------
    # Authority scope
    # ------------------------------------------------------------------

    def get_authority_scope(self, scope_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM authority_scope WHERE scope_id = ?", (scope_id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Trusted registry
    # ------------------------------------------------------------------

    def list_trusted_registry(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM trusted_registry").fetchall()

    def get_registry_entry(self, registry_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM trusted_registry WHERE registry_id = ?", (registry_id,)
        ).fetchone()

    # ------------------------------------------------------------------
    # Explicitly block mutation at the Python surface.
    # These are here to provide a clear error if someone tries to
    # add mutation methods — they should hit ProtectedConfigMutationError.
    # ------------------------------------------------------------------

    def _mutate_forbidden(self, *args, **kwargs) -> None:  # pragma: no cover
        raise ProtectedConfigMutationError(
            "Protected config is read-only at runtime. "
            "Seed config via migrations or a one-time seed script."
        )

    # Alias common mutation verbs so they fail loudly if accidentally called.
    insert = update = delete = upsert = _mutate_forbidden
