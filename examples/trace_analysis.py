"""Run the included static analysis and project a source-linked, portable trace."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from examples.offline_demo import demonstrate


def trace(out: Path) -> dict:
    first_use = demonstrate(out)
    relation = json.loads((out / "relation_map.json").read_text(encoding="utf-8"))
    validation = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
    unknowns = json.loads((out / "unknowns.json").read_text(encoding="utf-8"))
    nodes = {node["node_id"]: node for node in relation["nodes"]}
    calls = [edge for edge in relation["edges"] if edge["edge_type"] == "calls"]
    expected = {
        ("function:main.py:module:main", "function:helper.py:module:describe", 5),
        ("function:helper.py:module:describe", "function:formatting.py:module:label", 5),
        ("file:main.py", "function:main.py:module:main", 9),
    }
    assert {(e["source_id"], e["target_id"], e["lineno"]) for e in calls} == expected
    evidence = []
    for edge in calls:
        source_file = nodes[edge["source_id"]]["file_path"]
        source_line = (Path(__file__).parent / "tiny_repository" / source_file).read_text(encoding="utf-8").splitlines()[edge["lineno"] - 1].strip()
        assert edge["evidence"] in source_line
        evidence.append({"from": edge["source_id"], "to": edge["target_id"], "file": source_file, "line": edge["lineno"], "source": source_line})
    assert relation["node_count"] == 6 and relation["edge_count"] == 8
    assert validation["error_count"] == 0 and all(c["status"] == "pass" for c in validation["checks"])
    assert unknowns["total_unknown_count"] == 4
    return {
        "synthetic_input": True,
        "analysis": "Actual Python AST workflow; input files were not executed",
        "file_count": first_use["file_count"],
        "nodes": relation["node_count"],
        "edges": relation["edge_count"],
        "calls": evidence,
        "validation": {"passed": [c["check_id"] for c in validation["checks"]], "errors": validation["error_count"], "warnings": validation["warning_count"]},
        "unknowns": [{"source": section["source"], "items": section["items"]} for section in unknowns["sections"] if section["count"]],
        "model_calls": 0,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="reveng-trace-") as scratch:
        print(json.dumps(trace(Path(scratch) / "analysis"), indent=2))
