# Read the analysis as an evidence trail

RevEng turns explicit Python structure into an account you can inspect. The useful first question is: **where did this relationship come from?** The three-file example is deliberately small enough to answer without trusting a generated explanation.

## Run and inspect

From the installed checkout:

```sh
python -m examples.offline_demo --out output/first-analysis
python -m examples.trace_analysis
```

Use a new output directory for the first command. The second runs a fresh analysis in a temporary directory, checks the three expected call edges against source lines, and prints a portable [captured trace](../examples/trace-result.json). It excludes local roots, database records and timestamps. Neither path runs the analyzed files or calls a model.

## From one line to a relationship

[main.py](../examples/tiny_repository/main.py) imports `describe` from [helper.py](../examples/tiny_repository/helper.py), then calls it at line 5. The relation map records:

| Field | Value | Meaning |
|---|---|---|
| `source_id` | `function:main.py:module:main` | The containing function |
| `target_id` | `function:helper.py:module:describe` | The statically resolved target |
| `edge_type` | `calls` | A call expression, not merely an import |
| `lineno` | `5` | The evidence location in the source file |

`describe` in turn calls `label` in [formatting.py](../examples/tiny_repository/formatting.py). The module-level `main()` call at line 9 supplies the third call edge. With three file nodes, three function nodes, three containment edges and two import edges, the complete map contains **6 nodes and 8 edges**.

`print` is recorded separately as a builtin external call. It does not become an invented local function node.

## Which artifact answers which question?

| Artifact | Read it for |
|---|---|
| `repo_inventory.json` | Files scanned, parsed symbols and parse errors |
| `relation_map.json` | Nodes, explicit relations and unresolved/external targets |
| `file_breakdowns.json` | Each file's structural account |
| `enriched_file_breakdowns.json` | Derived file-level annotations |
| `subsystem_map.json` | Proposed groupings inferred from relationships |
| `flow_map.json` | Entry flows assembled from resolved calls |
| `repo_dossier.json` | A combined overview of those artifacts |
| `validation_report.json` | Internal consistency checks and warnings |
| `unknowns.json` | Remaining gaps and limits of the analysis |

The [workflow declaration](../reveng/analysis_engine/workflows/repo_analysis.py) shows the dependencies: scan, extract, inventory and relations precede the derived breakdowns, clusters and flows. Dossier, validation and unknowns consume those results. These are inspectable transformations, not runtime observations of the target application.

## A passing validation still has unknowns

The fixture passes six consistency checks with no errors or warnings. Four general limitations remain in `unknowns.json`: dynamic imports, conditional activation, stored function references/dynamic dispatch, and omitted unresolved call targets. Zero unresolved targets in this fixture does not make arbitrary Python behavior statically knowable.

For a real repository, inspect parse errors and unresolved targets before relying on the dossier. Check any proposed subsystem or flow against source. Keep the raw outputs local when the input repository is private; they can contain its paths and source details.

## Beyond the example

Run `reveng` for the local interface, keeping its default loopback binding. [ARCHITECTURE.md](../ARCHITECTURE.md) describes the wider capability/workflow control center. [SECURITY.md](../SECURITY.md) explains that enabling authored Python permits code with the host process's access; the static example needs no such user-code execution. Optional model and desktop integrations have separate configuration and are not demonstrated here.

A useful next investigation is a repository with explicit unresolved calls: compare each missing relation with its source and preserve the uncertainty, rather than treating a denser diagram as a more accurate analysis.
