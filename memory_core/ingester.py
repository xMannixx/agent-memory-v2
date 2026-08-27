"""Automatic Episode Ingestion for Memory Core v2.

Captures User/Assistant messages automatically and stores them as episodes.
Triggers consolidation after a configurable threshold.

Usage::

    from memory_core.ingester import EpisodeIngester

    ingester = EpisodeIngester(namespace="agent_main")

    # In a session hook or middleware:
    ingester.on_user_message("Ich wohne in Rielasingen")
    ingester.on_assistant_message("Notiert!")
    ingester.on_tool_call("web_search", "arriva", "Ergebnis...")

    # Auto-consolidation happens every N episodes (configurable)
    # Or trigger manually:
    ingester.consolidate_now(llm_provider)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from .config import Config, load_config
from .consolidator import Consolidator
from .episodes import EpisodeStore
from .facts import FactStore
from .llm import LLMProvider
from .router import StorageRouter
from .schema import init_schema

logger = logging.getLogger("memory_core.ingester")

_DEFAULT_CONSOLIDATE_EVERY = 10  # episodes


class EpisodeIngester:
    """Automatic episode ingestion with lazy consolidation.

    Captures messages as episodes and triggers consolidation after
    a configurable number of new episodes.

    Parameters
    ----------
    namespace : str
        Memory namespace.
    data_dir : str or None
        Override data directory.
    config : Config or None
        Override full configuration.
    consolidate_every : int
        Trigger consolidation after this many new episodes.
        Set to 0 to disable auto-consolidation.
    on_consolidate : callable or None
        Optional callback ``f(stats_dict)`` called after consolidation.
    """

    def __init__(
        self,
        namespace: str = "default",
        data_dir: Optional[str] = None,
        config: Optional[Config] = None,
        consolidate_every: int = _DEFAULT_CONSOLIDATE_EVERY,
        on_consolidate: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.namespace = namespace
        self._consolidate_every = consolidate_every
        self._on_consolidate = on_consolidate
        self._counter = 0
        self._lock = threading.Lock()

        # Configuration
        if config is not None:
            self._config = config
        else:
            import os
            if data_dir is not None:
                old = os.environ.get("MEMORY_CORE_STORAGE_DATA_DIR")
                os.environ["MEMORY_CORE_STORAGE_DATA_DIR"] = data_dir
                try:
                    self._config = load_config()
                finally:
                    if old is None:
                        os.environ.pop("MEMORY_CORE_STORAGE_DATA_DIR", None)
                    else:
                        os.environ["MEMORY_CORE_STORAGE_DATA_DIR"] = old
            else:
                self._config = load_config()

        # Storage
        self._router = StorageRouter(self._config)
        conn = self._router.connect(namespace)
        init_schema(conn)

        self._episodes = EpisodeStore(self._router)
        self._facts = FactStore(self._router)

    # -- Message Hooks --------------------------------------------------------

    def on_user_message(
        self,
        content: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record a user message as an episode.

        Returns
        -------
        str
            Episode ID.
        """
        return self._add(
            content, "user", "trusted_user",
            session_id=session_id, metadata=metadata,
        )

    def on_assistant_message(
        self,
        content: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record an assistant message as an episode.

        Returns
        -------
        str
            Episode ID.
        """
        return self._add(
            content, "assistant", "unknown",
            session_id=session_id, metadata=metadata,
        )

    def on_tool_call(
        self,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        *,
        session_id: Optional[str] = None,
    ) -> str:
        """Record a tool call as an episode.

        Returns
        -------
        str
            Episode ID.
        """
        content = f"Tool: {tool_name}\nInput: {tool_input}\nOutput: {tool_output}"
        return self._add(
            content, "tool", "tool_output",
            session_id=session_id, metadata={"tool": tool_name},
        )

    def on_system_message(
        self,
        content: str,
        *,
        session_id: Optional[str] = None,
    ) -> str:
        """Record a system message as an episode.

        Returns
        -------
        str
            Episode ID.
        """
        return self._add(
            content, "system", "unknown",
            session_id=session_id,
        )

    # -- Consolidation -------------------------------------------------------

    def consolidate_now(
        self,
        llm_provider: LLMProvider,
    ) -> Dict[str, Any]:
        """Trigger consolidation immediately.

        Parameters
        ----------
        llm_provider : LLMProvider
            The LLM provider for proposal generation.

        Returns
        -------
        dict
            Consolidation run statistics.
        """
        with self._lock:
            engine = Consolidator(
                self._router, self._config, llm_provider
            )
            stats = engine.run(self.namespace)
            self._counter = 0

            if self._on_consolidate:
                try:
                    self._on_consolidate(stats)
                except Exception:
                    logger.exception("on_consolidate callback failed")

            return stats

    def needs_consolidation(self) -> bool:
        """Check if enough episodes have accumulated for consolidation."""
        with self._lock:
            return (
                self._consolidate_every > 0
                and self._counter >= self._consolidate_every
            )

    @property
    def pending_count(self) -> int:
        """Number of episodes since last consolidation."""
        with self._lock:
            return self._counter

    # -- Stats ---------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        with self._lock:
            return self._facts.stats(self.namespace)

    def get_fact_count(self) -> int:
        """Return number of active facts."""
        return self.get_stats().get("active", 0)

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Close all database connections."""
        with self._lock:
            self._router.close_all()

    def __enter__(self) -> EpisodeIngester:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"EpisodeIngester(namespace={self.namespace!r}, "
            f"pending={self._counter})"
        )

    # -- Internal ------------------------------------------------------------

    def _add(
        self,
        content: str,
        role: str,
        origin: str,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Internal: add episode and check consolidation threshold."""
        with self._lock:
            ep_id = self._episodes.add(
                self.namespace,
                content,
                role,
                origin=origin,
                session_id=session_id,
                metadata=metadata or {},
            )
            self._counter += 1

            if (
                self._consolidate_every > 0
                and self._counter >= self._consolidate_every
            ):
                logger.info(
                    "Consolidation threshold reached (%d episodes). "
                    "Call consolidate_now(llm) to process.",
                    self._counter,
                )

            return ep_id
