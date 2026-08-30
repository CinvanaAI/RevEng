"""
Platform-owned durable capability package objects.

These records preserve the inspectable stored object that a live installed
capability record currently points at. Capability records remain the live index;
package objects preserve the durable package/version snapshot behind that index.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from sqlite3 import Row
from typing import Any


@dataclass
class CapabilityPackageObject:
    id: str
    capability_id: str
    version: str
    package_kind: str
    source_kind: str
    source_ref: str
    snapshot_data: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityPackageObject":
        return cls(
            id=row["id"],
            capability_id=row["capability_id"],
            version=row["version"],
            package_kind=row["package_kind"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            snapshot_data=json.loads(row["snapshot_json"] or "{}"),
            created_at=row["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability_id": self.capability_id,
            "version": self.version,
            "package_kind": self.package_kind,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "snapshot_data": self.snapshot_data,
            "created_at": self.created_at,
        }


__all__ = ["CapabilityPackageObject"]
