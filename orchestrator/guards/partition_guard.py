"""
Partition guard: enforces read/write access by role and partition.

Partitions:
  protected  — runtime read-only config (mission, policy, etc.)
  proposal   — writable by executor and validator; not by promoter-as-source
  durable    — promoter-only write path
  ephemeral  — runtime telemetry/validation/traces (runs, heartbeats, validator_results, etc.)

Roles:
  executor   — runs tasks, writes proposals and ephemeral rows
  validator  — reads proposals and ephemeral rows, writes validator_results
  promoter   — reads proposals + validator_results, writes durable rows + promotion_records
  synthesizer — FUTURE; reserved boundary; no slice-1 runtime path
"""
from __future__ import annotations

from typing import Literal

Partition = Literal["protected", "proposal", "durable", "ephemeral"]
Role = Literal["executor", "validator", "promoter", "synthesizer"]


class PartitionViolationError(Exception):
    """Raised when a role attempts a forbidden partition access."""


# ------------------------------------------------------------------
# Access matrix
# Read: what a role may read
# Write: what a role may write
# ------------------------------------------------------------------

_READ_ALLOWED: dict[str, set[str]] = {
    "executor":    {"protected", "proposal", "ephemeral"},
    "validator":   {"protected", "proposal", "ephemeral"},
    "promoter":    {"protected", "proposal", "ephemeral", "durable"},
    "synthesizer": set(),   # FUTURE — no runtime access in slice-1
}

_WRITE_ALLOWED: dict[str, set[str]] = {
    "executor":    {"proposal", "ephemeral"},
    "validator":   {"ephemeral"},           # validator_results live in ephemeral
    "promoter":    {"durable", "ephemeral"},# promotion_records + durable rows
    "synthesizer": set(),                   # FUTURE
}


def assert_can_read(role: str, partition: str) -> None:
    """Raise PartitionViolationError if role may not read from partition."""
    allowed = _READ_ALLOWED.get(role, set())
    if partition not in allowed:
        raise PartitionViolationError(
            f"Role '{role}' is not permitted to read from partition '{partition}'."
        )


def assert_can_write(role: str, partition: str) -> None:
    """Raise PartitionViolationError if role may not write to partition."""
    if partition == "protected":
        raise PartitionViolationError(
            f"Partition 'protected' is read-only at runtime. "
            f"Role '{role}' attempted a write."
        )
    allowed = _WRITE_ALLOWED.get(role, set())
    if partition not in allowed:
        raise PartitionViolationError(
            f"Role '{role}' is not permitted to write to partition '{partition}'."
        )


def assert_durable_write_is_promoter(role: str) -> None:
    """
    Shortcut guard: only the promoter role may write to the durable partition.
    Called at the entry of every durable repository write method.
    """
    if role != "promoter":
        raise PartitionViolationError(
            f"Durable writes require role='promoter'. Got role='{role}'."
        )
