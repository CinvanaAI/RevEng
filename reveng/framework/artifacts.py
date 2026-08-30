from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    kind: str


@dataclass(slots=True)
class ArtifactRecord:
    ref: ArtifactRef
    value: Any
    path: str | None = None
    views: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactStore:
    def __init__(self) -> None:
        self._records: dict[str, ArtifactRecord] = {}
        self._counter = 0
        self._lock = Lock()

    def put(
        self,
        kind: str,
        value: Any,
        *,
        path: str | Path | None = None,
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        with self._lock:
            self._counter += 1
            artifact_id = f"artifact-{self._counter}"

        ref = ArtifactRef(artifact_id=artifact_id, kind=kind)
        record = ArtifactRecord(
            ref=ref,
            value=value,
            path=str(path) if path is not None else None,
            views={key: str(item) for key, item in (views or {}).items()},
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._records[artifact_id] = record

        return ref

    def put_loaded(
        self,
        kind: str,
        path: str | Path,
        *,
        loader: Callable[[Path], Any],
        views: dict[str, str | Path] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        resolved = Path(path)
        value = loader(resolved)
        return self.put(
            kind,
            value,
            path=resolved,
            views=views,
            metadata=metadata,
        )

    def get(self, ref: ArtifactRef | str) -> ArtifactRecord:
        artifact_id = ref.artifact_id if isinstance(ref, ArtifactRef) else ref
        try:
            return self._records[artifact_id]
        except KeyError as exc:
            raise KeyError(f"Unknown artifact id: {artifact_id}") from exc

    def read(self, ref: ArtifactRef | str) -> Any:
        return self.get(ref).value

    def path(self, ref: ArtifactRef | str) -> str | None:
        return self.get(ref).path

    def views(self, ref: ArtifactRef | str) -> dict[str, str]:
        return dict(self.get(ref).views)
