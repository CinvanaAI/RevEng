"""Read-only filesystem explorer support for Agent Environment pickers."""
from __future__ import annotations

from pathlib import Path
from typing import Union


class FilesystemExplorerService:
    def resolve_root(self, root_path: Union[str, Path, None] = None) -> Path:
        if isinstance(root_path, Path):
            root = root_path.expanduser().resolve()
        elif isinstance(root_path, str) and root_path.strip():
            root = Path(root_path).expanduser().resolve()
        else:
            root = Path.cwd().resolve()
        if root.is_file():
            return root.parent
        return root

    def resolve_current_path(
        self,
        *,
        root_path: Union[str, Path, None] = None,
        current_path: Union[str, Path, None] = None,
    ) -> tuple[Path, Path]:
        root = self.resolve_root(root_path)
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
    ) -> dict[str, object]:
        root, current = self.resolve_current_path(root_path=root_path, current_path=current_path)
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
