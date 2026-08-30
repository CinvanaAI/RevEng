"""
Agent workflow runner — Coordination seam for agent-authored workflow execution.

Receives already-compiled Python workflow code, a resolved target, an output
path, and a live WorkflowRuntime. Execs the code in a controlled namespace,
calls the run(target, output_path) entry point, and returns whatever the
workflow returns.

This is a Coordination concern: it owns the seam between the platform submission
layer and the Framework runtime. It does not own the runtime itself (Framework)
or the workflow code (Agents domain).

Entry point convention
----------------------
The workflow code must define a top-level function:

    def run(target: str, output_path: str) -> dict:
        ...

The `if __name__ == "__main__":` block is NOT executed (name is set to
"__agent_workflow__").

Namespace
---------
The exec namespace receives:
  - capability_registry: CapabilityRegistryProxy bound to the runtime
  - run_id: str — the current run's ID, for evidence recording
  - __name__: "__agent_workflow__"

Standard library modules (json, ast, pathlib, etc.) are importable from
within the workflow code via normal Python import statements.
"""
from __future__ import annotations

from typing import Any

from reveng.framework.capability_proxy import CapabilityRegistryProxy
from reveng.framework.runtime import WorkflowRuntime
from reveng.framework.trusted_code import require_authored_code_execution_enabled


def run_agent_workflow(
    workflow_code: str,
    target: str,
    output_path: str,
    runtime: WorkflowRuntime,
) -> dict[str, Any]:
    """
    Execute agent workflow code and return the result dict from run().

    Parameters
    ----------
    workflow_code:
        Python source. Must define run(target, output_path) -> dict.
    target:
        Resolved target input (e.g. repo root path string) passed to run().
    output_path:
        Resolved output file path string passed to run().
    runtime:
        Live WorkflowRuntime. Provides capability dispatch and permission
        enforcement via CapabilityRegistryProxy.

    Returns
    -------
    dict returned by the workflow's run() function, or {} if run() returns None.

    Raises
    ------
    ValueError
        If the workflow code defines no callable run() function.
    Any exception raised by the workflow code propagates as-is.
    """
    require_authored_code_execution_enabled("agent-authored workflow code")
    proxy = CapabilityRegistryProxy(runtime, runtime.capability_registry)

    namespace: dict[str, Any] = {
        "__name__": "__agent_workflow__",
        "capability_registry": proxy,
        "run_id": runtime.run_id,
    }

    exec(compile(workflow_code, "<agent_workflow>", "exec"), namespace)  # noqa: S102

    run_fn = namespace.get("run")
    if run_fn is None or not callable(run_fn):
        raise ValueError(
            "Agent workflow code must define a top-level run(target, output_path) function. "
            "No callable 'run' was found after executing the workflow code."
        )

    result = run_fn(target, output_path)
    return result if isinstance(result, dict) else {}
