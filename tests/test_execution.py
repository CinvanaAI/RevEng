from __future__ import annotations

import threading
import unittest

from reveng.coordination.execution import AgenticExecutor


class _RuntimeStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._lock = threading.Lock()

    def invoke(self, capability_id: str, inputs: dict[str, object]) -> dict[str, object]:
        with self._lock:
            self.calls.append((capability_id, inputs))
        return {"capability_id": capability_id, **inputs}


class AgenticExecutorTests(unittest.TestCase):
    def test_invoke_delegates_to_runtime(self) -> None:
        runtime = _RuntimeStub()
        executor = AgenticExecutor(runtime)  # type: ignore[arg-type]

        result = executor.invoke("demo.echo", {"value": 7})

        self.assertEqual({"capability_id": "demo.echo", "value": 7}, result)
        self.assertEqual([("demo.echo", {"value": 7})], runtime.calls)

    def test_parallel_results_preserve_input_order(self) -> None:
        runtime = _RuntimeStub()
        executor = AgenticExecutor(runtime)  # type: ignore[arg-type]

        results = executor.invoke_parallel(
            [
                ("demo.first", {"position": 1}),
                ("demo.second", {"position": 2}),
                ("demo.third", {"position": 3}),
            ],
            max_workers=2,
        )

        self.assertEqual(
            ["demo.first", "demo.second", "demo.third"],
            [result["capability_id"] for result in results],
        )

    def test_parallel_empty_input_returns_empty_output(self) -> None:
        runtime = _RuntimeStub()
        executor = AgenticExecutor(runtime)  # type: ignore[arg-type]

        self.assertEqual([], executor.invoke_parallel([]))
        self.assertEqual([], runtime.calls)


if __name__ == "__main__":
    unittest.main()
