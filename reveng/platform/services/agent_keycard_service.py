"""Agents-owned file visibility and global tool-eligibility truth."""
from __future__ import annotations

import uuid
from pathlib import Path

from reveng.storage.db_connection import get_db
from reveng.platform.models.agent_file_assignment import AgentFileAssignmentRecord
from reveng.platform.services.agent_service import AgentService
from reveng.platform.services.agent_tool_file_permission_service import (
    AgentToolFilePermissionService,
)
from reveng.platform.utils import now_utc


def _ancestor_paths(path: str) -> list[str]:
    """Return normalized string paths for all ancestor directories of path."""
    return [str(ancestor) for ancestor in Path(path).parents]


class AgentKeycardService:
    def __init__(
        self,
        *,
        agent_service: AgentService | None = None,
        tool_file_permission_service: AgentToolFilePermissionService | None = None,
    ) -> None:
        self._agent_service = agent_service or AgentService()
        self._tool_file_permissions = (
            tool_file_permission_service or AgentToolFilePermissionService(agent_service=self._agent_service)
        )

    def list_assignments(
        self,
        agent_id: str,
        *,
        include_revoked: bool = False,
    ) -> list[AgentFileAssignmentRecord]:
        self._agent_service.get_or_raise(agent_id)
        with get_db() as conn:
            if include_revoked:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM agent_file_assignments
                    WHERE agent_id = ?
                    ORDER BY entry_kind ASC, relative_path ASC, absolute_path ASC
                    """,
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM agent_file_assignments
                    WHERE agent_id = ? AND visibility_state = 'granted'
                    ORDER BY entry_kind ASC, relative_path ASC, absolute_path ASC
                    """,
                    (agent_id,),
                ).fetchall()
        return [AgentFileAssignmentRecord.from_row(row) for row in rows]

    def assign_files(
        self,
        agent_id: str,
        *,
        root_path: str | Path,
        absolute_paths: list[str | Path],
    ) -> list[AgentFileAssignmentRecord]:
        self._agent_service.get_or_raise(agent_id)
        root = Path(root_path).expanduser().resolve()
        if root.is_file():
            root = root.parent
        normalized = self._normalize_file_paths(root=root, absolute_paths=absolute_paths)
        if not normalized:
            return []

        ts = now_utc()
        assigned: list[AgentFileAssignmentRecord] = []
        with get_db() as conn:
            for file_path in normalized:
                relative_path = self._relative_display_path(root, file_path)
                row = conn.execute(
                    """
                    SELECT *
                    FROM agent_file_assignments
                    WHERE agent_id = ? AND absolute_path = ?
                    """,
                    (agent_id, str(file_path)),
                ).fetchone()
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO agent_file_assignments (
                            id,
                            agent_id,
                            absolute_path,
                            root_path,
                            relative_path,
                            visibility_state,
                            global_tool_eligible,
                            entry_kind,
                            assigned_at,
                            revoked_at,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'granted', 0, 'file', ?, NULL, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            agent_id,
                            str(file_path),
                            str(root),
                            relative_path,
                            ts,
                            ts,
                            ts,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE agent_file_assignments
                        SET root_path = ?,
                            relative_path = ?,
                            visibility_state = 'granted',
                            entry_kind = 'file',
                            global_tool_eligible = CASE
                                WHEN visibility_state = 'granted' THEN global_tool_eligible
                                ELSE 0
                            END,
                            assigned_at = ?,
                            revoked_at = NULL,
                            updated_at = ?
                        WHERE agent_id = ? AND absolute_path = ?
                        """,
                        (str(root), relative_path, ts, ts, agent_id, str(file_path)),
                    )
            conn.commit()

        for file_path in normalized:
            assigned.append(self.get_assignment_or_raise(agent_id, str(file_path)))
        return assigned

    def assign_folder(
        self,
        agent_id: str,
        *,
        root_path: str | Path,
        absolute_path: str | Path,
    ) -> AgentFileAssignmentRecord:
        """
        Add a directory to the Keycard as a folder entry.

        A folder entry grants visibility to all files inside the directory,
        recursively.  The entry_kind is stored as 'folder'.  Global tool
        eligibility defaults to off and can be toggled via set_global_eligibility.
        """
        self._agent_service.get_or_raise(agent_id)
        root = Path(root_path).expanduser().resolve()
        if root.is_file():
            root = root.parent
        folder_path = Path(absolute_path).expanduser().resolve()
        if not folder_path.exists() or not folder_path.is_dir():
            raise ValueError(f"Assigned path is not a readable directory: {folder_path}")
        if not self._is_within_root(folder_path, root):
            raise ValueError(
                f"Assigned folder {folder_path} is outside the selected explorer root {root}."
            )
        relative_path = self._relative_display_path(root, folder_path)
        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_file_assignments
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (agent_id, str(folder_path)),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_file_assignments (
                        id,
                        agent_id,
                        absolute_path,
                        root_path,
                        relative_path,
                        visibility_state,
                        global_tool_eligible,
                        entry_kind,
                        assigned_at,
                        revoked_at,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'granted', 0, 'folder', ?, NULL, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        agent_id,
                        str(folder_path),
                        str(root),
                        relative_path,
                        ts,
                        ts,
                        ts,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE agent_file_assignments
                    SET root_path = ?,
                        relative_path = ?,
                        visibility_state = 'granted',
                        entry_kind = 'folder',
                        assigned_at = ?,
                        revoked_at = NULL,
                        updated_at = ?
                    WHERE agent_id = ? AND absolute_path = ?
                    """,
                    (str(root), relative_path, ts, ts, agent_id, str(folder_path)),
                )
            conn.commit()
        return self.get_assignment_or_raise(agent_id, str(folder_path))

    def remove_file(self, agent_id: str, absolute_path: str | Path) -> None:
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_file_assignments
                SET visibility_state = 'revoked',
                    global_tool_eligible = 0,
                    revoked_at = ?,
                    updated_at = ?
                WHERE agent_id = ? AND absolute_path = ? AND visibility_state = 'granted'
                """,
                (ts, ts, agent_id, normalized),
            )
            conn.commit()
        self._tool_file_permissions.clear_for_file(agent_id, normalized)

    def set_global_eligibility(
        self,
        agent_id: str,
        absolute_path: str | Path,
        *,
        enabled: bool,
    ) -> AgentFileAssignmentRecord:
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
        existing = self.get_assignment_or_raise(agent_id, normalized)
        if not existing.is_visible:
            raise ValueError("Entry is not currently assigned to this agent's Keycard.")
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_file_assignments
                SET global_tool_eligible = ?,
                    updated_at = ?
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (1 if enabled else 0, ts, agent_id, normalized),
            )
            conn.commit()
        if enabled and not existing.is_folder:
            # For file entries: explicitly sync tool permissions as before.
            # For folder entries: no explicit rows needed — is_tool_allowed_on_file
            # checks ancestor folder grants dynamically.
            self._tool_file_permissions.sync_for_global_enabled_file(agent_id, normalized)
        elif not enabled:
            self._tool_file_permissions.clear_for_file(agent_id, normalized)
        return self.get_assignment_or_raise(agent_id, normalized)

    def is_file_visible_to_agent(self, agent_id: str, absolute_path: str | Path) -> bool:
        """
        Return True when the file is visible to the agent.

        Visibility is granted when:
        - the file has a direct 'granted' entry in agent_file_assignments, OR
        - any ancestor directory has a folder 'granted' entry.
        """
        normalized = str(Path(absolute_path).expanduser().resolve())
        ancestors = _ancestor_paths(normalized)
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT visibility_state
                FROM agent_file_assignments
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (agent_id, normalized),
            ).fetchone()
            if row is not None and str(row["visibility_state"]) == "granted":
                return True
            if ancestors:
                placeholders = ",".join("?" * len(ancestors))
                folder_row = conn.execute(
                    f"""
                    SELECT 1 FROM agent_file_assignments
                    WHERE agent_id = ?
                      AND entry_kind = 'folder'
                      AND visibility_state = 'granted'
                      AND absolute_path IN ({placeholders})
                    """,
                    (agent_id, *ancestors),
                ).fetchone()
                if folder_row is not None:
                    return True
        return False

    def is_file_globally_eligible(self, agent_id: str, absolute_path: str | Path) -> bool:
        """
        Return True when the file is globally tool-eligible for the agent.

        Global eligibility is granted when:
        - the file has a direct entry with global_tool_eligible=1, OR
        - any ancestor directory has a folder entry with global_tool_eligible=1.
        """
        normalized = str(Path(absolute_path).expanduser().resolve())
        ancestors = _ancestor_paths(normalized)
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT visibility_state, global_tool_eligible
                FROM agent_file_assignments
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (agent_id, normalized),
            ).fetchone()
            if (
                row is not None
                and str(row["visibility_state"]) == "granted"
                and bool(row["global_tool_eligible"])
            ):
                return True
            if ancestors:
                placeholders = ",".join("?" * len(ancestors))
                folder_row = conn.execute(
                    f"""
                    SELECT 1 FROM agent_file_assignments
                    WHERE agent_id = ?
                      AND entry_kind = 'folder'
                      AND visibility_state = 'granted'
                      AND global_tool_eligible = 1
                      AND absolute_path IN ({placeholders})
                    """,
                    (agent_id, *ancestors),
                ).fetchone()
                if folder_row is not None:
                    return True
        return False

    def list_visible_file_paths(self, agent_id: str, *, repo_root: str | Path | None = None) -> list[str]:
        """
        Return the set of file paths visible to the agent.

        For file entries: the file path itself (if it exists on disk).
        For folder entries: all files found recursively inside the folder.
        """
        root = self._normalize_repo_root(repo_root) if repo_root is not None else None
        paths: set[str] = set()
        for assignment in self.list_assignments(agent_id):
            if assignment.is_folder:
                folder = Path(assignment.absolute_path)
                if folder.is_dir():
                    for f in folder.rglob("*"):
                        if f.is_file() and (root is None or self._is_within_root(f, root)):
                            paths.add(str(f.resolve()))
            else:
                p = Path(assignment.absolute_path)
                if p.is_file() and (root is None or self._is_within_root(p, root)):
                    paths.add(assignment.absolute_path)
        return sorted(paths)

    def list_globally_eligible_file_paths(
        self,
        agent_id: str,
        *,
        repo_root: str | Path | None = None,
    ) -> list[str]:
        """
        Return the set of files that are globally tool-eligible for the agent.

        For file entries: the file path itself (when global_tool_eligible=True).
        For folder entries: all files found recursively inside (when global_tool_eligible=True).
        """
        root = self._normalize_repo_root(repo_root) if repo_root is not None else None
        paths: set[str] = set()
        for assignment in self.list_assignments(agent_id):
            if not assignment.global_tool_eligible:
                continue
            if assignment.is_folder:
                folder = Path(assignment.absolute_path)
                if folder.is_dir():
                    for f in folder.rglob("*"):
                        if f.is_file() and (root is None or self._is_within_root(f, root)):
                            paths.add(str(f.resolve()))
            else:
                p = Path(assignment.absolute_path)
                if p.is_file() and (root is None or self._is_within_root(p, root)):
                    paths.add(assignment.absolute_path)
        return sorted(paths)

    def build_run_visibility_context(self, agent_id: str, repo_path: str | Path) -> dict[str, object]:
        repo_root = self._normalize_repo_root(repo_path)
        visible = self.list_visible_file_paths(agent_id, repo_root=repo_root)
        global_eligible = self.list_globally_eligible_file_paths(agent_id, repo_root=repo_root)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT capability_id
                FROM agent_capability_assignments
                WHERE agent_id = ? AND assignment_state = 'granted'
                ORDER BY capability_id ASC
                """,
                (agent_id,),
            ).fetchall()
        tool_allowed = {
            str(row["capability_id"]): [
                path
                for path in self._tool_file_permissions.list_granted_file_paths(
                    agent_id,
                    str(row["capability_id"]),
                )
                if Path(path).exists() and self._is_within_root(Path(path), repo_root)
            ]
            for row in rows
        }
        return {
            "repo_root": str(repo_root),
            "visible_file_paths": visible,
            "global_tool_eligible_file_paths": global_eligible,
            "tool_allowed_file_paths": tool_allowed,
        }

    def get_assignment_or_raise(
        self,
        agent_id: str,
        absolute_path: str | Path,
    ) -> AgentFileAssignmentRecord:
        normalized = str(Path(absolute_path).expanduser().resolve())
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_file_assignments
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (agent_id, normalized),
            ).fetchone()
        if row is None:
            raise KeyError(
                f"File assignment not found for agent {agent_id!r} and path {normalized!r}"
            )
        return AgentFileAssignmentRecord.from_row(row)

    def _normalize_file_paths(
        self,
        *,
        root: Path,
        absolute_paths: list[str | Path],
    ) -> list[Path]:
        normalized: list[Path] = []
        seen: set[str] = set()
        for value in absolute_paths:
            file_path = Path(value).expanduser().resolve()
            if not file_path.exists() or not file_path.is_file():
                raise ValueError(f"Assigned path is not a readable file: {file_path}")
            if not self._is_within_root(file_path, root):
                raise ValueError(
                    f"Assigned file {file_path} is outside the selected explorer root {root}."
                )
            normalized_value = str(file_path)
            if normalized_value in seen:
                continue
            seen.add(normalized_value)
            normalized.append(file_path)
        return normalized

    def _relative_display_path(self, root: Path, file_path: Path) -> str:
        try:
            return file_path.relative_to(root).as_posix()
        except ValueError:
            return file_path.name

    def _normalize_repo_root(self, repo_path: str | Path) -> Path:
        resolved = Path(repo_path).expanduser().resolve()
        if resolved.is_file():
            return resolved.parent
        return resolved

    def _is_within_root(self, file_path: Path, root: Path) -> bool:
        try:
            file_path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False


__all__ = ["AgentKeycardService"]
