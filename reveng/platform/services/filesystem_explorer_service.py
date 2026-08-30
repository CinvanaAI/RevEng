"""Read-only filesystem explorer support for Agent Environment pickers."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Union


class FilesystemExplorerService:
    @staticmethod
    def _as_directory(path: Union[str, Path]) -> Path:
        resolved = Path(path).expanduser().resolve()
        return resolved.parent if resolved.is_file() else resolved

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def resolve_root(
        self,
        root_path: Union[str, Path, None] = None,
        *,
        allowed_roots: Iterable[Union[str, Path]] | None = None,
    ) -> Path:
        if isinstance(root_path, Path):
            root = self._as_directory(root_path)
        elif isinstance(root_path, str) and root_path.strip():
            root = self._as_directory(root_path)
        else:
            root = Path.cwd().resolve()

        allowed = [self._as_directory(path) for path in (allowed_roots or [])]
        allowed = list(dict.fromkeys(allowed))
        if allowed and not any(self._is_within(root, candidate) for candidate in allowed):
            return allowed[0]
        return root

    def resolve_current_path(
        self,
        *,
        root_path: Union[str, Path, None] = None,
        current_path: Union[str, Path, None] = None,
        allowed_roots: Iterable[Union[str, Path]] | None = None,
    ) -> tuple[Path, Path]:
        root = self.resolve_root(root_path, allowed_roots=allowed_roots)
        if isinstance(current_path, Path):
            current = current_path.expanduser().resolve()
        elif isinstance(current_path, str) and current_path.strip():
            current = Path(current_path).expanduser().resolve()
        else:
            current = root
        if current.is_file():
            current = current.parent
        try:
            current.relative_to(root)
        except ValueError:
            current = root
        return root, current

    def list_directory(
        self,
        *,
        root_path: Union[str, Path, None] = None,
        current_path: Union[str, Path, None] = None,
        allowed_roots: Iterable[Union[str, Path]] | None = None,
    ) -> dict[str, object]:
        root, current = self.resolve_current_path(
            root_path=root_path,
            current_path=current_path,
            allowed_roots=allowed_roots,
        )
        entries: list[dict[str, object]] = []
        if current.exists() and current.is_dir():
            for entry in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                try:
                    relative_path = entry.relative_to(root).as_posix()
                except ValueError:
                    relative_path = entry.name
                entries.append(
                    {
                        "name": entry.name,
                        "absolute_path": str(entry.resolve()),
                        "relative_path": relative_path,
                        "entry_type": "directory" if entry.is_dir() else "file",
                        "assignable": entry.is_file(),
                    }
                )
        parent_path: str | None = None
        if current != root:
            parent_path = str(current.parent.resolve())
        return {
            "root_path": str(root),
            "current_path": str(current),
            "parent_path": parent_path,
            "entries": entries,
        }


__all__ = ["FilesystemExplorerService"]
