# Architecture

RevEng separates repository interpretation, runtime execution, platform authority, and presentation so each layer has a clear job.

## Component boundaries

| Area | Responsibility |
| --- | --- |
| `reveng/analysis_engine` | Static analysis passes, meaning derivation, report composition, capability packs, and built-in workflows. |
| `reveng/framework` | Capability contracts, workflow execution, caching, artifacts, and structured runtime logging. |
| `reveng/coordination` | Default host composition, workflow routing, and bounded concurrent capability execution. |
| `reveng/platform` | Durable capability, agent, provider, run, permission, publication, and rollback services. |
| `reveng/storage` | SQLite connection ownership, schema migrations, and framework-log persistence. |
| `reveng/execution_environment` | Agent and capability workspaces, navigation semantics, appearance assets, and file-keycard interaction. |
| `reveng/integration` | Optional OpenAI-compatible and Ollama provider adapters. |

## Analysis lifecycle

1. A run is submitted from the API or control center.
2. Platform services resolve the agent, provider, tool grants, and visible file keycard.
3. Coordination builds a host using the storage-backed capability catalog.
4. The runtime checks capability permission before every invocation.
5. Analysis capabilities produce staged artifacts: inventory, relations, breakdowns, clusters, flows, reports, and optional meaning records.
6. Run status, events, framework logs, and output references are persisted to SQLite.

## Capability lifecycle

1. Built-in pack registrars seed executable definitions into the durable catalog.
2. A draft can propose a function or composite capability.
3. Validation checks the contract, execution source, importable binding or code block, composite ordering, and component availability.
4. Publication creates an immutable package snapshot and installs or replaces live truth.
5. Runtime registries resolve the installed record into an executable definition.
6. Publication history or a saved draft revision can be used to roll back.

The catalog is authoritative; an in-memory registry is only an execution projection. This prevents the UI, database, and workflow host from quietly carrying different capability inventories.

## Trust boundaries

- File access is scoped by the agent keycard and tool-file permission service.
- Capability use is scoped by agent assignments and checked inside `WorkflowRuntime.invoke`.
- Provider secrets are read from a local `.env` file and are never stored in the repository.
- The server is intended for localhost and has no built-in authentication.
- Generated databases and analysis artifacts may contain source paths or repository content and must not be committed.
