"""Run and heartbeat models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Run:
    run_id: str
    task_id: str
    work_item_id: Optional[str]
    role: str               # 'executor' | 'validator' | 'promoter'
    status: str             # 'running' | 'completed' | 'failed' | 'expired'
    started_at: str
    expires_at: str
    attempt_no: int
    parent_run_id: Optional[str]


@dataclass
class RunHeartbeat:
    heartbeat_id: str
    run_id: str
    timestamp: str
    status: str
    progress_note: Optional[str]
