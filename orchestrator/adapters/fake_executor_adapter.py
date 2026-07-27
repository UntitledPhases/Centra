"""
Fake executor adapter for tests and local development.

Supports:
- valid output (schema_valid=True, declared_completion_status='completed')
- malformed output (schema_valid=False, bad declared_completion_status)
- configurable content and artifact type
- call counting for retry-path tests
"""
from __future__ import annotations

from typing import List, Optional

from orchestrator.adapters.protocols import ExecutorAdapterResult
from orchestrator.models.task import WorkItem


class FakeExecutorAdapter:
    """
    Returns a configurable ExecutorAdapterResult.
    Thread-safe for sequential use (tests run sequentially).
    """

    def __init__(
        self,
        valid: bool = True,
        content: bytes = b'{"result": "synthesized content", "source": "internal"}',
        artifact_type: str = "synthesis_result",
        observation_content: Optional[bytes] = None,
    ) -> None:
        self._valid = valid
        self._content = content
        self._artifact_type = artifact_type
        self._observation_content = observation_content
        self.call_count: int = 0

    def execute(
        self,
        work_item: WorkItem,
        source_artifact_refs: List[str],
        context: dict,
    ) -> ExecutorAdapterResult:
        self.call_count += 1
        if self._valid:
            return ExecutorAdapterResult(
                content=self._content,
                artifact_type=self._artifact_type,
                schema_valid=True,
                declared_completion_status="completed",
                self_check="self-check advisory: output looks reasonable",
                observation_content=self._observation_content,
            )
        return ExecutorAdapterResult(
            content=b"malformed-output",
            artifact_type=self._artifact_type,
            schema_valid=False,
            declared_completion_status="malformed",
            self_check="self-check advisory: executor encountered an error",
            observation_content=None,
        )


class OnceFailThenSucceedExecutorAdapter:
    """
    Returns malformed output on the first call, valid output on subsequent calls.
    Used to test the single-retry path.
    """

    def __init__(
        self,
        content: bytes = b'{"result": "retry succeeded"}',
        artifact_type: str = "synthesis_result",
    ) -> None:
        self._content = content
        self._artifact_type = artifact_type
        self.call_count: int = 0

    def execute(
        self,
        work_item: WorkItem,
        source_artifact_refs: List[str],
        context: dict,
    ) -> ExecutorAdapterResult:
        self.call_count += 1
        if self.call_count == 1:
            return ExecutorAdapterResult(
                content=b"malformed-first-attempt",
                artifact_type=self._artifact_type,
                schema_valid=False,
                declared_completion_status="malformed",
                self_check="first attempt failed",
                observation_content=None,
            )
        return ExecutorAdapterResult(
            content=self._content,
            artifact_type=self._artifact_type,
            schema_valid=True,
            declared_completion_status="completed",
            self_check="retry succeeded",
            observation_content=None,
        )
