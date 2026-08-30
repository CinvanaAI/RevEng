"""
Platform-owned CapabilityDraft models.

Capability drafts are non-live capability work units. They remain outside the
installed registry, but their schema, lifecycle, revision semantics, and
publication records belong to the Capability Platform rather than to any single
environment UI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from sqlite3 import Row
from typing import Any


CAPABILITY_DRAFT_STATES = ("draft", "published", "retired")
CAPABILITY_DRAFT_ITEM_STATES = ("draft", "validated", "published")


class CapabilityDraftNotFoundError(KeyError):
    pass


@dataclass
class CapabilityDraftRecord:
    """Storage row for a non-live CapabilityDraft."""

    id: str
    name: str
    description: str
    lifecycle_state: str
    version: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityDraftRecord":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            lifecycle_state=row["lifecycle_state"],
            version=row["version"] if "version" in row.keys() else "1.0.0",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class CapabilityDraftRevisionRecord:
    """A saved working-version snapshot for a CapabilityDraft."""

    id: str
    draft_id: str
    version: str
    name: str
    description: str
    saved_at: str
    item_count: int
    snapshot_data: dict[str, Any]

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityDraftRevisionRecord":
        return cls(
            id=row["id"],
            draft_id=row["draft_id"],
            version=row["version"],
            name=row["name"],
            description=row["description"],
            saved_at=row["saved_at"],
            item_count=row["item_count"],
            snapshot_data=json.loads(row["snapshot_data"] or "{}"),
        )


@dataclass
class CapabilityDraftPublicationRecord:
    """A single publication event for a CapabilityDraft."""

    id: str
    draft_id: str
    version: str
    published_at: str
    item_count: int

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityDraftPublicationRecord":
        return cls(
            id=row["id"],
            draft_id=row["draft_id"],
            version=row["version"],
            published_at=row["published_at"],
            item_count=row["item_count"],
        )


@dataclass
class CapabilityDraftItem:
    """
    A single capability object being authored within a CapabilityDraft.

    `planned_capability_id` is the intended live capability_id. `draft_data`
    holds the authored object state while it remains non-live.
    """

    id: str
    draft_id: str
    planned_capability_id: str
    draft_data: dict[str, Any]
    item_state: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Row) -> "CapabilityDraftItem":
        return cls(
            id=row["id"],
            draft_id=row["draft_id"],
            planned_capability_id=row["planned_capability_id"],
            draft_data=json.loads(row["draft_data"] or "{}"),
            item_state=row["item_state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class CapabilityDraftSpec:
    """A CapabilityDraft assembled with its authored draft items."""

    draft: CapabilityDraftRecord
    items: list[CapabilityDraftItem] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.draft.id

    @property
    def name(self) -> str:
        return self.draft.name

    @property
    def lifecycle_state(self) -> str:
        return self.draft.lifecycle_state

    @property
    def item_count(self) -> int:
        return len(self.items)


__all__ = [
    "CAPABILITY_DRAFT_ITEM_STATES",
    "CAPABILITY_DRAFT_STATES",
    "CapabilityDraftItem",
    "CapabilityDraftNotFoundError",
    "CapabilityDraftPublicationRecord",
    "CapabilityDraftRecord",
    "CapabilityDraftRevisionRecord",
    "CapabilityDraftSpec",
]
