"""Narrative Store for Memory Core v2.

Manages the versioned narrative layer.
"""

from __future__ import annotations

from typing import Optional

from .config import Config
from .ids import narrative_id
from .models import Narrative
from .router import StorageRouter
from .utils import utc_now_iso


class NarrativeStore:
    """Manages reading and writing to the narratives table."""

    def __init__(self, router: StorageRouter, config: Config) -> None:
        self._router = router
        self._config = config

    def get_latest(self, namespace: str) -> Optional[Narrative]:
        """Fetch the most recent narrative for the given namespace."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, namespace, version, content, created_at, created_by "
            "FROM narratives "
            "WHERE namespace = ? "
            "ORDER BY version DESC LIMIT 1",
            (namespace,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return Narrative(
            id=row[0],
            namespace=row[1],
            version=row[2],
            content=row[3],
            created_at=row[4],
            created_by=row[5],
        )

    def write(self, namespace: str, content: str, by: str) -> str:
        """Write a new version of the narrative. Returns the new ID.

        Uses a deterministic content-hash ID (INV-1) instead of uuid4.
        """
        latest = self.get_latest(namespace)
        next_version = (latest.version + 1) if latest else 1

        nar_id = narrative_id(namespace, next_version)
        now = utc_now_iso()

        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO narratives "
            "(id, namespace, version, content, created_at, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nar_id, namespace, next_version, content, now, by)
        )
        conn.commit()
        return nar_id
