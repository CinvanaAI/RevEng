"""Agents-owned per-tool file permission truth."""
from __future__ import annotations

import uuid
from pathlib import Path

from reveng.storage.db_connection import get_db
from reveng.platform.models.agent_tool_file_permission import (
    AgentToolFilePermissionRecord,
)
from reveng.platform.services.agent_service import AgentService
from reveng.platform.utils import now_utc


class AgentToolFilePermissionService:
    def __init__(self, *, agent_service: AgentService | None = None) -> None:
        self._agent_service = agent_service or AgentService()

    def list_permissions(
        self,
        agent_id: str,
        *,
        capability_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[AgentToolFilePermissionRecord]:
        self._agent_service.get_or_raise(agent_id)
        clauses = ["agent_id = ?"]
        params: list[object] = [agent_id]
        if capability_id is not None:
            clauses.append("capability_id = ?")
            params.append(capability_id)
        if not include_revoked:
            clauses.append("permission_state = 'granted'")
        query = (
            "SELECT * FROM agent_tool_file_permissions "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY capability_id ASC, absolute_path ASC"
        )
        with get_db() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [AgentToolFilePermissionRecord.from_row(row) for row in rows]

    def list_granted_file_paths(self, agent_id: str, capability_id: str) -> list[str]:
        """
        Return all file paths the agent may use for this capability.

        Includes:
        - files with an explicit granted agent_tool_file_permissions record
        - files found recursively inside globally-eligible folder Keycard entries
        - files found recursively inside per-tool folder grants (agent_tool_file_permissions
          records where the stored path is a directory)
        """
        explicit_files: list[str] = []
        folder_files: list[str] = []
        for record in self.list_permissions(agent_id, capability_id=capability_id):
            p = Path(record.absolute_path)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        folder_files.append(str(f.resolve()))
            else:
                explicit_files.append(record.absolute_path)
        # Also expand globally-eligible folder Keycard entries
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT absolute_path FROM agent_file_assignments
                WHERE agent_id = ?
                  AND entry_kind = 'folder'
                  AND visibility_state = 'granted'
                  AND global_tool_eligible = 1
                """,
                (agent_id,),
            ).fetchall()
        for row in rows:
            folder = Path(str(row["absolute_path"]))
            if folder.is_dir():
                for f in folder.rglob("*"):
                    if f.is_file():
                        folder_files.append(str(f.resolve()))
        return sorted(set(explicit_files + folder_files))

    def is_tool_allowed_on_file(
        self,
        agent_id: str,
        capability_id: str,
        absolute_path: str | Path,
    ) -> bool:
        """
        Return True when the agent is allowed to use this capability on this file.

        Allowed when:
        - an explicit agent_tool_file_permissions record exists with permission_state='granted', OR
        - the file is inside a per-tool folder grant (a folder path stored in
          agent_tool_file_permissions for this capability with permission_state='granted'), OR
        - the file is inside a globally-eligible folder Keycard entry (entry_kind='folder',
          visibility_state='granted', global_tool_eligible=1).
        """
        normalized = str(Path(absolute_path).expanduser().resolve())
        ancestors = [str(p) for p in Path(normalized).parents]
        with get_db() as conn:
            # Check 1: explicit per-file record
            row = conn.execute(
                """
                SELECT permission_state
                FROM agent_tool_file_permissions
                WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                """,
                (agent_id, capability_id, normalized),
            ).fetchone()
            if row is not None and str(row["permission_state"]) == "granted":
                return True
            if ancestors:
                placeholders = ",".join("?" * len(ancestors))
                # Check 2: per-tool folder grant in agent_tool_file_permissions
                tool_folder_row = conn.execute(
                    f"""
                    SELECT 1 FROM agent_tool_file_permissions
                    WHERE agent_id = ?
                      AND capability_id = ?
                      AND permission_state = 'granted'
                      AND absolute_path IN ({placeholders})
                    """,
                    (agent_id, capability_id, *ancestors),
                ).fetchone()
                if tool_folder_row is not None:
                    return True
                # Check 3: globally-eligible folder Keycard entry
                kc_folder_row = conn.execute(
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
                if kc_folder_row is not None:
                    return True
        return False

    def set_allowed(
        self,
        agent_id: str,
        capability_id: str,
        absolute_path: str | Path,
        *,
        allowed: bool,
        source_kind: str = "manual",
    ) -> AgentToolFilePermissionRecord | None:
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
        self._ensure_tool_granted(agent_id, capability_id)
        if allowed:
            # Only enforce global eligibility when granting; revoking always works.
            self._ensure_visible_and_globally_eligible(agent_id, normalized)
        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_tool_file_permissions
                WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                """,
                (agent_id, capability_id, normalized),
            ).fetchone()
            if allowed:
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO agent_tool_file_permissions (
                            id,
                            agent_id,
                            capability_id,
                            absolute_path,
                            permission_state,
                            source_kind,
                            granted_at,
                            revoked_at,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, 'granted', ?, ?, NULL, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            agent_id,
                            capability_id,
                            normalized,
                            source_kind,
                            ts,
                            ts,
                            ts,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE agent_tool_file_permissions
                        SET permission_state = 'granted',
                            source_kind = ?,
                            granted_at = ?,
                            revoked_at = NULL,
                            updated_at = ?
                        WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                        """,
                        (source_kind, ts, ts, agent_id, capability_id, normalized),
                    )
            else:
                conn.execute(
                    """
                    UPDATE agent_tool_file_permissions
                    SET permission_state = 'revoked',
                        revoked_at = ?,
                        updated_at = ?
                    WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                    """,
                    (ts, ts, agent_id, capability_id, normalized),
                )
            conn.commit()
        if not allowed:
            return None
        return self.get_permission_or_raise(agent_id, capability_id, normalized)

    def sync_for_new_granted_tool(self, agent_id: str, capability_id: str) -> None:
        # Only sync explicit rows for file entries.  Files inside folder entries
        # are handled dynamically by is_tool_allowed_on_file — no explicit rows needed.
        self._agent_service.get_or_raise(agent_id)
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT absolute_path
                FROM agent_file_assignments
                WHERE agent_id = ?
                  AND entry_kind = 'file'
                  AND visibility_state = 'granted'
                  AND global_tool_eligible = 1
                ORDER BY relative_path ASC, absolute_path ASC
                """,
                (agent_id,),
            ).fetchall()
        for row in rows:
            self.set_allowed(
                agent_id,
                capability_id,
                str(row["absolute_path"]),
                allowed=True,
                source_kind="global_sync",
            )

    def sync_for_global_enabled_file(self, agent_id: str, absolute_path: str | Path) -> None:
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
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
        for row in rows:
            self.set_allowed(
                agent_id,
                str(row["capability_id"]),
                normalized,
                allowed=True,
                source_kind="global_sync",
            )

    def clear_for_file(self, agent_id: str, absolute_path: str | Path) -> None:
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_tool_file_permissions
                SET permission_state = 'revoked',
                    revoked_at = ?,
                    updated_at = ?
                WHERE agent_id = ? AND absolute_path = ? AND permission_state = 'granted'
                """,
                (ts, ts, agent_id, normalized),
            )
            conn.commit()

    def clear_for_tool(self, agent_id: str, capability_id: str) -> None:
        self._agent_service.get_or_raise(agent_id)
        ts = now_utc()
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_tool_file_permissions
                SET permission_state = 'revoked',
                    revoked_at = ?,
                    updated_at = ?
                WHERE agent_id = ? AND capability_id = ? AND permission_state = 'granted'
                """,
                (ts, ts, agent_id, capability_id),
            )
            conn.commit()

    def get_permission_or_raise(
        self,
        agent_id: str,
        capability_id: str,
        absolute_path: str | Path,
    ) -> AgentToolFilePermissionRecord:
        normalized = str(Path(absolute_path).expanduser().resolve())
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_tool_file_permissions
                WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                """,
                (agent_id, capability_id, normalized),
            ).fetchone()
        if row is None:
            raise KeyError(
                f"Tool-file permission not found for agent {agent_id!r}, "
                f"capability {capability_id!r}, file {normalized!r}"
            )
        return AgentToolFilePermissionRecord.from_row(row)

    def grant_direct(
        self,
        agent_id: str,
        capability_id: str,
        absolute_path: str | Path,
    ) -> AgentToolFilePermissionRecord:
        """
        Grant this capability access to a file or folder path without requiring
        global eligibility.  The path must already be in the agent's Keycard
        (caller's responsibility).  Use this for per-tool Keycard assignment.

        Unlike set_allowed(), this does not check global_tool_eligible.
        Folder paths are stored as-is; is_tool_allowed_on_file() resolves their
        contents dynamically via the ancestor-folder check.
        """
        self._agent_service.get_or_raise(agent_id)
        normalized = str(Path(absolute_path).expanduser().resolve())
        self._ensure_tool_granted(agent_id, capability_id)
        if not self._is_path_visible(agent_id, normalized):
            raise ValueError("Path is not in this agent's Keycard.")
        ts = now_utc()
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM agent_tool_file_permissions
                WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                """,
                (agent_id, capability_id, normalized),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_tool_file_permissions (
                        id, agent_id, capability_id, absolute_path,
                        permission_state, source_kind,
                        granted_at, revoked_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 'granted', 'direct', ?, NULL, ?, ?)
                    """,
                    (str(uuid.uuid4()), agent_id, capability_id, normalized, ts, ts, ts),
                )
            else:
                conn.execute(
                    """
                    UPDATE agent_tool_file_permissions
                    SET permission_state = 'granted',
                        source_kind = 'direct',
                        granted_at = ?,
                        revoked_at = NULL,
                        updated_at = ?
                    WHERE agent_id = ? AND capability_id = ? AND absolute_path = ?
                    """,
                    (ts, ts, agent_id, capability_id, normalized),
                )
            conn.commit()
        return self.get_permission_or_raise(agent_id, capability_id, normalized)

    def _is_path_visible(self, agent_id: str, absolute_path: str) -> bool:
        """Return True if path has a direct or ancestor-folder Keycard entry."""
        ancestors = [str(p) for p in Path(absolute_path).parents]
        with get_db() as conn:
            row = conn.execute(
                "SELECT visibility_state FROM agent_file_assignments WHERE agent_id=? AND absolute_path=?",
                (agent_id, absolute_path),
            ).fetchone()
            if row and str(row["visibility_state"]) == "granted":
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

    def _ensure_visible_and_globally_eligible(self, agent_id: str, absolute_path: str) -> None:
        ancestors = [str(p) for p in Path(absolute_path).parents]
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT visibility_state, global_tool_eligible
                FROM agent_file_assignments
                WHERE agent_id = ? AND absolute_path = ?
                """,
                (agent_id, absolute_path),
            ).fetchone()
            if row is not None and str(row["visibility_state"]) == "granted":
                if not bool(row["global_tool_eligible"]):
                    raise ValueError("File is visible but not globally tool-eligible for this agent.")
                return
            # Check ancestor folder grants
            if ancestors:
                placeholders = ",".join("?" * len(ancestors))
                folder_row = conn.execute(
                    f"""
                    SELECT global_tool_eligible FROM agent_file_assignments
                    WHERE agent_id = ?
                      AND entry_kind = 'folder'
                      AND visibility_state = 'granted'
                      AND absolute_path IN ({placeholders})
                    """,
                    (agent_id, *ancestors),
                ).fetchone()
                if folder_row is not None:
                    if not bool(folder_row["global_tool_eligible"]):
                        raise ValueError(
                            "File is visible via folder grant but the folder is not globally "
                            "tool-eligible for this agent."
                        )
                    return
        raise ValueError("File is not currently assigned to this agent's Keycard.")

    def _ensure_tool_granted(self, agent_id: str, capability_id: str) -> None:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM agent_capability_assignments
                WHERE agent_id = ? AND capability_id = ? AND assignment_state = 'granted'
                """,
                (agent_id, capability_id),
            ).fetchone()
        if row is None:
            raise ValueError("Capability package is not currently granted to this agent.")


__all__ = ["AgentToolFilePermissionService"]
