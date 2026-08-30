"""
CapabilitySurfacePolicyService — gating semantic layer.

Gating is a service-level semantic concept, not just router checks. This service
is the authoritative policy checker for any surface access operation.

Table: capability_surface_policies
    capability_id  — NULL means platform-wide policy
    surface_name   — 'unpublished_source' | 'published_python' | 'history' | etc.
    consumer_kind  — 'human_admin' | 'agent' | 'api_consumer' | '*'
    access_policy  — 'allow' | 'deny' | 'require_gate'

Resolution order:
  1. Capability-specific policy matching consumer_kind exactly
  2. Capability-specific policy matching consumer_kind='*'
  3. Platform-wide policy matching consumer_kind exactly
  4. Platform-wide policy matching consumer_kind='*'
  5. Default: allow (open by default unless a policy explicitly denies)

Router enforcement and service-level checks are both valid manifestations of
this gating layer. The service is the authority; the router is one consumer.
"""
from __future__ import annotations

import uuid
from typing import Any

from reveng.storage.db_connection import get_db
from reveng.platform.utils import now_utc


class CapabilitySurfacePolicyService:
    """
    Policy authority for capability surface access.

    check() returns True if access is allowed, False if denied or gated.
    """

    def check(
        self,
        capability_id: str | None,
        surface_name: str,
        consumer_kind: str,
    ) -> bool:
        """
        Return True if access to *surface_name* is allowed for *consumer_kind*.

        Checks capability-specific policies first, then platform-wide.
        Returns True (allow) when no policy matches.
        """
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """
                    SELECT capability_id, consumer_kind, access_policy
                    FROM capability_surface_policies
                    WHERE surface_name = ?
                      AND access_policy != 'allow'
                    ORDER BY
                        CASE WHEN capability_id IS NOT NULL THEN 0 ELSE 1 END ASC,
                        CASE WHEN consumer_kind = ? THEN 0 ELSE 1 END ASC
                    """,
                    (surface_name, consumer_kind),
                ).fetchall()
        except Exception:
            return True  # No table or query error → allow

        for row in rows:
            cap_match = (row["capability_id"] is None) or (row["capability_id"] == capability_id)
            kind_match = (row["consumer_kind"] == "*") or (row["consumer_kind"] == consumer_kind)
            if cap_match and kind_match:
                return row["access_policy"] == "allow"

        return True  # Default: allow

    def list_policies(
        self,
        capability_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all policies, optionally filtered by capability_id."""
        try:
            with get_db() as conn:
                if capability_id is not None:
                    rows = conn.execute(
                        """
                        SELECT * FROM capability_surface_policies
                        WHERE capability_id = ? OR capability_id IS NULL
                        ORDER BY surface_name ASC, consumer_kind ASC
                        """,
                        (capability_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM capability_surface_policies
                        ORDER BY surface_name ASC, consumer_kind ASC
                        """
                    ).fetchall()
        except Exception:
            return []

        return [
            {
                "id": row["id"],
                "capability_id": row["capability_id"],
                "surface_name": row["surface_name"],
                "consumer_kind": row["consumer_kind"],
                "access_policy": row["access_policy"],
                "notes": row["notes"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def set_policy(
        self,
        *,
        surface_name: str,
        consumer_kind: str,
        access_policy: str,
        capability_id: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Upsert a surface policy.

        access_policy must be 'allow', 'deny', or 'require_gate'.
        Returns the upserted policy dict.
        """
        if access_policy not in ("allow", "deny", "require_gate"):
            raise ValueError(f"access_policy must be 'allow', 'deny', or 'require_gate', got {access_policy!r}")
        ts = now_utc()
        policy_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO capability_surface_policies
                    (id, capability_id, surface_name, consumer_kind, access_policy, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_policy = excluded.access_policy,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (policy_id, capability_id, surface_name, consumer_kind, access_policy, notes, ts, ts),
            )
            conn.commit()
        return {
            "id": policy_id,
            "capability_id": capability_id,
            "surface_name": surface_name,
            "consumer_kind": consumer_kind,
            "access_policy": access_policy,
            "notes": notes,
            "created_at": ts,
            "updated_at": ts,
        }

    def delete_policy(self, policy_id: str) -> bool:
        """Delete a policy by ID. Returns True if a row was deleted."""
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM capability_surface_policies WHERE id = ?",
                (policy_id,),
            )
            conn.commit()
        return cursor.rowcount > 0


__all__ = ["CapabilitySurfacePolicyService"]
