"""Episode Log for Memory Core v2.

Append-only raw interaction records.  The single source of truth from
which facts and narratives are derived (spec §3).

Episodes are searchable via FTS5 and CLI, but **never** prompt-injected
(INV-9).  At runtime, adapters write only episodes (INV-3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .ids import episode_id as _make_episode_id
from .models import Episode, row_to_episode
from .router import StorageRouter

logger = logging.getLogger("memory_core.episodes")

# Episode origin vocabulary (spec §6.2).
VALID_ORIGINS = frozenset({
    "trusted_user",
    "local_project",
    "trusted_tool_output",
    "tool_output",
    "external_web",
    "external_document",
    "unknown",
})

# Valid episode roles.
VALID_ROLES = frozenset({"user", "assistant", "tool", "system"})

# Default expiry for episodes (spec §4.1).
_DEFAULT_EXPIRY_DAYS = 90

# Anomaly detection: writes-per-minute threshold (carried from v3.6).
_ANOMALY_WRITES_PER_MINUTE = 60

# Select columns in canonical order.
_EPISODE_COLUMNS = (
    "id, namespace, session_id, role, origin, content, metadata, "
    "created_at, expires_at, consumed_by"
)


class EpisodeStore:
    """Manages the Episode Log for a ``StorageRouter``.

    Parameters
    ----------
    router:
        The storage router to use for connections.
    """

    def __init__(self, router: StorageRouter) -> None:
        self._router = router
        self._write_timestamps: List[float] = []

    # -- write ----------------------------------------------------------------

    def add(
        self,
        namespace: str,
        content: str,
        role: str,
        origin: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires_in_days: int = _DEFAULT_EXPIRY_DAYS,
    ) -> str:
        """Append an episode to the log.  Returns the episode ID.

        Raises ``ValueError`` on invalid *role* or *origin*.
        """
        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role {role!r}; expected one of {sorted(VALID_ROLES)}"
            )
        if origin not in VALID_ORIGINS:
            raise ValueError(
                f"Invalid origin {origin!r}; "
                f"expected one of {sorted(VALID_ORIGINS)}"
            )
        if not content or not content.strip():
            raise ValueError("Episode content must not be empty")

        now = _utc_now()
        now_iso = now.isoformat()
        ep_id = _make_episode_id(content, session_id or "", now_iso)

        expires_at: Optional[str] = None
        if expires_in_days > 0:
            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        conn = self._router.connect(namespace)
        cursor = conn.cursor()

        # Idempotency: skip if already exists (content-hash ID).
        cursor.execute("SELECT 1 FROM episodes WHERE id = ?", (ep_id,))
        if cursor.fetchone() is not None:
            return ep_id

        cursor.execute(
            f"INSERT INTO episodes ({_EPISODE_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ep_id, namespace, session_id, role, origin, content,
                meta_json, now_iso, expires_at, None,
            ),
        )
        conn.commit()

        self._check_anomaly()
        return ep_id

    # -- read -----------------------------------------------------------------

    def search(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 20,
    ) -> List[Episode]:
        """Full-text search over episodes in *namespace*."""
        conn = self._router.connect(namespace)
        fts_query = _safe_fts_query(query)
        if not fts_query:
            return []

        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_EPISODE_COLUMNS} FROM episodes "
            "WHERE namespace = ? AND rowid IN ("
            "    SELECT rowid FROM episodes_fts WHERE episodes_fts MATCH ?"
            ") ORDER BY created_at DESC LIMIT ?",
            (namespace, fts_query, limit),
        )
        return [row_to_episode(row) for row in cursor.fetchall()]

    def list_unconsumed(
        self,
        namespace: str,
        *,
        limit: int = 200,
    ) -> List[Episode]:
        """Return unconsumed episodes, oldest first (for the consolidator)."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_EPISODE_COLUMNS} FROM episodes "
            "WHERE namespace = ? AND consumed_by IS NULL "
            "ORDER BY created_at ASC LIMIT ?",
            (namespace, limit),
        )
        return [row_to_episode(row) for row in cursor.fetchall()]

    def list_recent(
        self,
        namespace: str,
        *,
        limit: int = 50,
    ) -> List[Episode]:
        """Return most recent episodes, newest first."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_EPISODE_COLUMNS} FROM episodes "
            "WHERE namespace = ? ORDER BY created_at DESC LIMIT ?",
            (namespace, limit),
        )
        return [row_to_episode(row) for row in cursor.fetchall()]

    def get(self, namespace: str, episode_id: str) -> Optional[Episode]:
        """Return a single episode by ID, or ``None``."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_EPISODE_COLUMNS} FROM episodes "
            "WHERE namespace = ? AND id = ?",
            (namespace, episode_id),
        )
        row = cursor.fetchone()
        return row_to_episode(row) if row else None

    def mark_consumed(
        self,
        namespace: str,
        episode_ids: List[str],
        run_id: str,
    ) -> int:
        """Mark episodes as consumed by a consolidation run.

        Returns the number of rows updated.
        """
        if not episode_ids:
            return 0
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in episode_ids)
        cursor.execute(
            f"UPDATE episodes SET consumed_by = ? "
            f"WHERE namespace = ? AND id IN ({placeholders}) "
            "AND consumed_by IS NULL",
            [run_id, namespace] + list(episode_ids),
        )
        conn.commit()
        return cursor.rowcount

    # -- maintenance ----------------------------------------------------------

    def forget_stale(self, namespace: str) -> int:
        """Remove expired episodes.  Returns count of deleted rows."""
        now_iso = _utc_now().isoformat()
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM episodes "
            "WHERE namespace = ? AND expires_at IS NOT NULL AND expires_at < ?",
            (namespace, now_iso),
        )
        conn.commit()
        return cursor.rowcount

    def stats(self, namespace: str) -> Dict[str, Any]:
        """Return episode statistics for *namespace*."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM episodes WHERE namespace = ?",
            (namespace,),
        )
        total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM episodes "
            "WHERE namespace = ? AND consumed_by IS NULL",
            (namespace,),
        )
        unconsumed = cursor.fetchone()[0]

        cursor.execute(
            "SELECT role, COUNT(*) FROM episodes "
            "WHERE namespace = ? GROUP BY role",
            (namespace,),
        )
        by_role = dict(cursor.fetchall())

        cursor.execute(
            "SELECT origin, COUNT(*) FROM episodes "
            "WHERE namespace = ? GROUP BY origin",
            (namespace,),
        )
        by_origin = dict(cursor.fetchall())

        return {
            "total": total,
            "unconsumed": unconsumed,
            "by_role": by_role,
            "by_origin": by_origin,
        }

    # -- anomaly detection (carried from v3.6) --------------------------------

    def _check_anomaly(self) -> None:
        """Track writes/minute and log a warning if the threshold is
        exceeded."""
        now = time.monotonic()
        self._write_timestamps.append(now)

        # Trim to the last 60 seconds.
        cutoff = now - 60
        self._write_timestamps = [
            ts for ts in self._write_timestamps if ts > cutoff
        ]

        if len(self._write_timestamps) > _ANOMALY_WRITES_PER_MINUTE:
            logger.warning(
                "Episode intake anomaly: %d writes in the last 60s "
                "(threshold: %d)",
                len(self._write_timestamps),
                _ANOMALY_WRITES_PER_MINUTE,
            )


# -- helpers ------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_fts_query(query: str) -> str:
    """Build a safe FTS5 query from user input.

    Extracts word tokens (``\\w+``), filters short ones, and joins with
    ``OR`` using token-prefix matching (``term*``).
    """
    terms = re.findall(r"\w+", query)
    safe_terms = [t for t in terms if len(t) >= 2]
    if not safe_terms:
        return ""
    return " OR ".join(f"{t}*" for t in safe_terms)
