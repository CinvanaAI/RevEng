# RevEng

Inspect an unfamiliar Python repository and get source-linked structural maps, reports and explicit unknowns.

## Try it

Python 3.11+. Run from this checkout:

```sh
python -m pip install -e .
python -m examples.offline_demo --out output/first-analysis
```

**Input:** Three small Python files with explicit imports and function calls.

**Result:** The static workflow writes a file inventory, relationship map, per-file breakdowns, dossier, validation and unknowns. It does not execute the input repository or call a model.

See [the captured example](examples/RESULT.md) for the observed output and reproduction command.

## How it works

An inspectable architecture account starts from source symbols and relationships, then carries evidence into derived reports. Explicit unknowns show where static analysis cannot resolve behavior.

Source: [reveng/cli.py](reveng/cli.py), [reveng/analysis_engine/workflows/repo_analysis.py](reveng/analysis_engine/workflows/repo_analysis.py), [tests/test_host_workflow.py](tests/test_host_workflow.py).

## Use it for your work

Run `reveng` for the local browser interface, then choose a Python repository you want to understand. Start with the included `examples/tiny_repository`; output folders must be new. Prefer a short runtime path on Windows. See [ASSETS.md](ASSETS.md) for interface-asset provenance.

## Beyond the first analysis

The local control center also manages reusable capabilities, composite workflows, agent permissions, run evidence and publication history. These are implemented surfaces with their own contracts; the first static analysis does not require configuring them. [ARCHITECTURE.md](ARCHITECTURE.md) maps the components and [SECURITY.md](SECURITY.md) explains the local HTTP boundary and trusted authored-code setting.

Keep the default loopback binding. Optional user-authored Python runs with the host process’s access after explicit enablement; capability keycards are not an operating-system sandbox.

## Scope

Static relationships and inferred behavior are provisional. Dynamic imports/calls and framework behavior may remain unresolved. Optional model/desktop surfaces need their own configuration; the first example uses neither.

Owned code is available under the [MIT license](LICENSE).
