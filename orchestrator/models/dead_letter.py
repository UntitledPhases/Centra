"""Dead-letter entry model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DeadLetterEntry:
    dead_letter_id: str
    task_id: Optional[str]
    run_id: Optional[str]
    failure_class: str      # required
    reason: str             # required
    retry_count: int
    timestamp: str
