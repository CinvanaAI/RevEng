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

        requested_workers = max_workers or len(ordered_calls)
        worker_count = max(1, min(int(requested_workers), len(ordered_calls)))

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="reveng-capability",
        ) as pool:
            futures = [
                pool.submit(self.invoke, capability_id, inputs)
                for capability_id, inputs in ordered_calls
            ]
            return [future.result() for future in futures]
