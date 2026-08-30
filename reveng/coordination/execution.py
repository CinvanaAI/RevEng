"""Bounded capability execution helpers.

The analysis workflows use this adapter when independent capability calls can
run concurrently.  It deliberately delegates every call to
``WorkflowRuntime.invoke`` so permission checks, artifact tracking, and
structured framework logging remain authoritative.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterable

from reveng.framework.runtime import WorkflowRuntime

CapabilityCall = tuple[str, dict[str, Any]]
MAX_PARALLEL_WORKERS = 8


def bounded_worker_count(requested_workers: int | None, task_count: int) -> int:
    if task_count <= 0:
        return 0
    requested = requested_workers or task_count
    return max(1, min(int(requested), task_count, MAX_PARALLEL_WORKERS))


class AgenticExecutor:
    """Invoke registered capabilities serially or in a bounded thread pool."""

    def __init__(self, runtime: WorkflowRuntime) -> None:
        self.runtime = runtime

    def invoke(self, capability_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.invoke(capability_id, inputs)

    def invoke_parallel(
        self,
        calls: Iterable[CapabilityCall],
        *,
        max_workers: int | None = None,
    ) -> list[dict[str, Any]]:
        ordered_calls = list(calls)
        if not ordered_calls:
            return []

        worker_count = bounded_worker_count(max_workers, len(ordered_calls))

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="reveng-capability",
        ) as pool:
            futures = [
                pool.submit(self.invoke, capability_id, inputs)
                for capability_id, inputs in ordered_calls
            ]
            return [future.result() for future in futures]


__all__ = [
    "AgenticExecutor",
    "CapabilityCall",
    "MAX_PARALLEL_WORKERS",
    "bounded_worker_count",
]
