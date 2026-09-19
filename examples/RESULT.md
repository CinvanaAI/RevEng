# Recorded first use

This output was produced by the included example with network connections disabled. Synthetic provider or worker replies are identified by the example; no real model quality or billing is implied.

From the installed checkout:

```sh
python -m examples.offline_demo
```

[Complete recorded output](result.json)

```text
{
  "mode": "Actual static analysis; included synthetic source",
  "file_count": 3,
  "source_files": [
    "formatting.py",
    "helper.py",
    "main.py"
  ],
  "artifacts": {
    "inventory_path": "repo_inventory.json",
    "relation_map_path": "relation_map.json",
    "file_breakdowns_path": "file_breakdowns.json",
    "enriched_path": "enriched_file_breakdowns.json",
    "cluster_map_path": "subsystem_map.json",
    "flow_map_path": "flow_map.json",
    "repo_dossier_path": "repo_dossier.json",
    "validation_report_path": "validation_report.json",
    "unknowns_path": "unknowns.json"
  },
  "model_calls": 0
}
```

Generated timestamps and synthetic identifiers can change between runs. The demonstrated behavior and input fixture remain inspectable in the adjacent example files.
