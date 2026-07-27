"""
Test 6: Protected config mutation attempt fails.

protected config is read-only at runtime.
The repository surface must not expose insert/update/delete.
"""
from __future__ import annotations

import pytest

from orchestrator.repositories.protected_config import (
    ProtectedConfigRepository,
    ProtectedConfigMutationError,
)


class TestProtectedConfigReadOnly:

    def test_insert_alias_raises(self, protected_repo):
        with pytest.raises(ProtectedConfigMutationError):
            protected_repo.insert("anything")

    def test_update_alias_raises(self, protected_repo):
        with pytest.raises(ProtectedConfigMutationError):
            protected_repo.update("anything")

    def test_delete_alias_raises(self, protected_repo):
        with pytest.raises(ProtectedConfigMutationError):
            protected_repo.delete("anything")

    def test_upsert_alias_raises(self, protected_repo):
        with pytest.raises(ProtectedConfigMutationError):
            protected_repo.upsert("anything")

    def test_direct_db_insert_to_mission_is_possible_only_by_seed_path(self, conn):
        """
        Direct DB insert can bypass the repo layer (seed scripts use raw SQL).
        We verify that the table is writable at DB level (seeding works),
        while the repo surface has no write methods.
        """
        conn.execute(
            """
            INSERT INTO mission (mission_id, name, description, created_at)
            VALUES ('m1', 'Test Mission', 'For testing', '2025-01-01T00:00:00+00:00')
            """
        )
        conn.commit()

        from orchestrator.repositories.protected_config import ProtectedConfigRepository
        repo = ProtectedConfigRepository(conn)
        row = repo.get_mission("m1")
        assert row is not None
        assert row["name"] == "Test Mission"

    def test_list_missions_reads_seeded_data(self, conn, protected_repo):
        conn.execute(
            """
            INSERT INTO mission (mission_id, name, description, created_at)
            VALUES ('m2', 'Mission Alpha', 'Alpha', '2025-01-01T00:00:00+00:00')
            """
        )
        conn.commit()
        missions = protected_repo.list_missions()
        assert any(m["mission_id"] == "m2" for m in missions)

    def test_no_write_methods_on_repo_surface(self):
        """
        Verify the repo class has no public write methods beyond the blocked aliases.
        """
        import inspect
        repo_cls = ProtectedConfigRepository
        public_methods = [
            name for name, _ in inspect.getmembers(repo_cls, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        write_verbs = {"create", "save", "persist", "write", "put", "set"}
        for method_name in public_methods:
            for verb in write_verbs:
                assert not method_name.startswith(verb), (
                    f"ProtectedConfigRepository should not have write method: {method_name}"
                )
