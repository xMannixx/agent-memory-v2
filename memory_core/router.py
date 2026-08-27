"""Storage router for Memory Core v2.

Resolves namespace → SQLite connection.  Supports two topologies
(spec §5):

    ``single``
        One DB file (``<data_dir>/memory.db``) for all namespaces.
    ``per-namespace``
        One DB file per namespace (``<data_dir>/<sanitized_ns>.db``).

INV-10 enforcement:
    - Write calls carry exactly one namespace.
    - ``shared`` namespace accepts writes only via the review queue
      (logged warning at router level; hard enforcement in B2).
    - Read calls may request ``namespace + shared`` merge.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from . import schema
from .config import Config

logger = logging.getLogger("memory_core.router")


def _sanitize_namespace(ns: str) -> str:
    """Turn a namespace into a safe filename component.

    ``:`` is mapped to ``__`` (spec §5).
    """
    return ns.replace(":", "__")


class StorageRouter:
    """Resolve namespace → SQLite connection(s).

    Parameters
    ----------
    config:
        The loaded ``Config`` instance.
    db_path_override:
        If set, ignore topology and use this single path (for tests with
        ``:memory:`` or a temp file).
    """

    def __init__(
        self,
        config: Config,
        *,
        db_path_override: Optional[str] = None,
    ) -> None:
        self._config = config
        self._mode = config.storage.mode
        self._data_dir = config.resolved_data_dir
        self._override = db_path_override

        # Connection cache: path → connection.
        self._connections: dict[str, sqlite3.Connection] = {}
        self._lock = threading.Lock()

        if self._override is None:
            self._data_dir.mkdir(parents=True, exist_ok=True)

    # -- public API -----------------------------------------------------------

    def connect(self, namespace: str) -> sqlite3.Connection:
        """Return a writable connection for *namespace*.

        The schema is initialised automatically on first access.
        """
        path = self._resolve_path(namespace)
        return self._get_or_create(path)

    def connect_read(
        self,
        namespace: str,
        *,
        include_shared: bool = False,
    ) -> List[sqlite3.Connection]:
        """Return connection(s) for reading.

        When *include_shared* is ``True``, returns
        ``[own_ns_conn, shared_conn]`` (deduplicated if they resolve to
        the same DB).
        """
        own_path = self._resolve_path(namespace)
        paths = [own_path]

        if include_shared and namespace != "shared":
            shared_path = self._resolve_path("shared")
            if shared_path != own_path:
                paths.append(shared_path)

        return [self._get_or_create(p) for p in paths]

    def warn_shared_write(self, namespace: str) -> None:
        """Log a warning if a write targets ``shared`` outside the review
        queue.  Hard enforcement is added in B2 (gate pipeline)."""
        if namespace == "shared":
            logger.warning(
                "Direct write to 'shared' namespace detected.  "
                "Under INV-10, shared writes should go through the "
                "review queue."
            )

    def close_all(self) -> None:
        """Close all cached connections."""
        with self._lock:
            for conn in self._connections.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    # -- internals ------------------------------------------------------------

    def _resolve_path(self, namespace: str) -> str:
        """Map a namespace to a DB file path (or ``:memory:``)."""
        if self._override is not None:
            return self._override

        if self._mode == "per-namespace":
            safe_name = _sanitize_namespace(namespace)
            return str(self._data_dir / f"{safe_name}.db")

        # single mode
        return str(self._data_dir / "memory.db")

    def _get_or_create(self, path: str) -> sqlite3.Connection:
        """Return a cached connection or create + initialise a new one."""
        with self._lock:
            if path in self._connections:
                return self._connections[path]

            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            schema.init_schema(conn)
            self._connections[path] = conn
            return conn
