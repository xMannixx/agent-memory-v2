"""OpenClaw Bridge for Memory Core v2.

Provides a high-level API for integrating Memory Core with OpenClaw agents.
Handles episode ingestion from session transcripts, memory context injection
into system prompts, and background consolidation with thread-safety.

Usage::

    from memory_core.adapters.openclaw_bridge import MemoryBridge

    bridge = MemoryBridge(namespace="agent_main", data_dir="~/.memory-core")

    # Ingest a conversation turn
    bridge.add_interaction("user", "Was ist mein Beruf?", origin="conversation")
    bridge.add_interaction("assistant", "Du bist Schichtleiter.", origin="conversation")

    # Get memory context for system prompt
    context = bridge.get_memory_context(query="Beruf Arbeit")

    # Trigger background consolidation (optional, requires LLM)
    bridge.consolidate_background(llm_provider)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from ..config import load_config, Config
from ..consolidator import Consolidator
from ..episodes import EpisodeStore
from ..facts import FactStore
from ..injection import get_injection_block
from ..narratives import NarrativeStore
from ..router import StorageRouter
from ..schema import init_schema

logger = logging.getLogger("memory_core.openclaw_bridge")


class MemoryBridge:
    """High-level bridge between OpenClaw and Memory Core v2.

    This is the primary integration point for OpenClaw agents. It manages:
    - Episode ingestion from session transcripts
    - Memory context generation for system prompts
    - Background consolidation (optional)
    - Thread-safe access to all stores

    Parameters
    ----------
    namespace : str
        The memory namespace (e.g. ``"agent_main"``, ``"agent_alice"``).
    data_dir : str or None
        Override the data directory. Defaults to ``~/.memory-core``.
    config : Config or None
        Override the full configuration. If provided, *data_dir* is ignored.
    """

    def __init__(
        self,
        namespace: str = "default",
        data_dir: Optional[str] = None,
        config: Optional[Config] = None,
    ) -> None:
        self.namespace = namespace
        self._lock = threading.Lock()

        # Configuration
        if config is not None:
            self.config = config
        else:
            import os
            if data_dir is not None:
                os.environ["MEMORY_CORE_STORAGE_DATA_DIR"] = data_dir
            self.config = load_config()

        # Storage
        self.router = StorageRouter(self.config)
        conn = self.router.connect(namespace)
        init_schema(conn)

        # Stores
        self.episodes = EpisodeStore(self.router)
        self.facts = FactStore(self.router)
        self.narratives = NarrativeStore(self.router, self.config)

    # -- Episode Ingestion ----------------------------------------------------

    def add_interaction(
        self,
        role: str,
        content: str,
        *,
        origin: str = "unknown",
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record a single interaction as an episode.

        Parameters
        ----------
        role : str
            One of ``user``, ``assistant``, ``tool``, ``system``.
        content : str
            The message content.
        origin : str
            The origin vocabulary (default ``conversation``).
        session_id : str or None
            Optional session identifier for grouping.
        metadata : dict or None
            Optional metadata dict.

        Returns
        -------
        str
            The episode ID.
        """
        with self._lock:
            return self.episodes.add(
                self.namespace,
                content,
                role,
                origin=origin,
                session_id=session_id,
                metadata=metadata or {},
            )

    def add_conversation_turn(
        self,
        user_message: str,
        assistant_message: str,
        *,
        session_id: Optional[str] = None,
        user_origin: str = "trusted_user",
        assistant_origin: str = "unknown",
    ) -> List[str]:
        """Convenience: record a full user+assistant turn as two episodes.

        Returns
        -------
        list[str]
            The two episode IDs ``[user_ep_id, assistant_ep_id]``.
        """
        ep1 = self.add_interaction(
            "user", user_message,
            origin=user_origin, session_id=session_id,
        )
        ep2 = self.add_interaction(
            "assistant", assistant_message,
            origin=assistant_origin, session_id=session_id,
        )
        return [ep1, ep2]

    def add_tool_call(
        self,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        *,
        session_id: Optional[str] = None,
    ) -> str:
        """Record a tool call as an episode.

        Parameters
        ----------
        tool_name : str
            The tool name (e.g. ``web_search``, ``exec``).
        tool_input : str
            The tool input/arguments.
        tool_output : str
            The tool output/result.

        Returns
        -------
        str
            The episode ID.
        """
        content = f"Tool: {tool_name}\nInput: {tool_input}\nOutput: {tool_output}"
        return self.add_interaction(
            "tool", content,
            origin="tool_output", session_id=session_id,
            metadata={"tool": tool_name},
        )

    # -- Memory Context -------------------------------------------------------

    def get_memory_context(
        self,
        query: Optional[str] = None,
        *,
        max_chars: Optional[int] = None,
        include_shared: bool = True,
    ) -> str:
        """Generate the ``# Memory Context`` block for injection into
        the system prompt.

        Parameters
        ----------
        query : str or None
            Optional query for relevance-based fact retrieval.
            If ``None``, returns narrative + recent facts.
        max_chars : int or None
            Override the character limit from config.
        include_shared : bool
            Whether to include the ``shared`` namespace.

        Returns
        -------
        str
            The formatted memory context block, or empty string.
        """
        with self._lock:
            block = get_injection_block(
                self.namespace,
                self.narratives,
                self.facts,
                self.config,
            )

            if max_chars and len(block) > max_chars:
                block = block[:max_chars] + "..."

            return block

    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        authority_class: Optional[str] = None,
        include_shared: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search memory and return facts as dicts.

        Parameters
        ----------
        query : str
            The search query.
        limit : int
            Maximum results.
        authority_class : str or None
            Filter by lane (e.g. ``identity``, ``preference``).
        include_shared : bool
            Include the ``shared`` namespace.

        Returns
        -------
        list[dict]
            List of fact dictionaries.
        """
        with self._lock:
            facts = self.facts.recall(
                self.namespace,
                query,
                limit=limit,
                authority_class=authority_class,
                include_shared=include_shared,
            )
            return [f.to_dict() for f in facts]

    def get_facts(
        self,
        *,
        authority_class: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List all active facts, optionally filtered by lane.

        Returns
        -------
        list[dict]
            List of fact dictionaries.
        """
        with self._lock:
            facts = self.facts.list_facts(
                self.namespace,
                authority_class=authority_class,
                limit=limit,
            )
            return [f.to_dict() for f in facts]

    def get_stats(self) -> Dict[str, Any]:
        """Return memory statistics for this namespace."""
        with self._lock:
            return self.facts.stats(self.namespace)

    # -- Consolidation --------------------------------------------------------

    def consolidate(
        self,
        llm_provider: Any,
    ) -> Dict[str, Any]:
        """Run the consolidation engine.

        Fetches unconsumed episodes, calls the LLM for proposals, and
        processes them through the gate pipeline.

        Parameters
        ----------
        llm_provider : LLMProvider
            An LLM provider instance (e.g. ``OpenAILlm``, ``OllamaLlm``).
            Must implement ``LLMProvider.generate_proposals()``.

        Returns
        -------
        dict
            Run statistics.
        """
        from ..llm import LLMProvider
        if not isinstance(llm_provider, LLMProvider):
            raise TypeError(
                f"llm_provider must implement LLMProvider, "
                f"got {type(llm_provider).__name__}"
            )

        with self._lock:
            engine = Consolidator(
                self.router, self.config, llm_provider
            )
            return engine.run(self.namespace)

    def consolidate_background(
        self,
        llm_provider: Any,
        callback: Optional[Any] = None,
    ) -> threading.Thread:
        """Run consolidation in a background thread.

        Useful for non-blocking memory digestion during agent operation.

        Parameters
        ----------
        llm_provider : LLMProvider
            The LLM provider.
        callback : callable or None
            Optional callback ``f(stats_dict)`` called after completion.

        Returns
        -------
        threading.Thread
            The background thread (already started).
        """
        def _worker() -> None:
            try:
                result = self.consolidate(llm_provider)
                if callback:
                    callback(result)
            except Exception:
                logger.exception("Background consolidation failed")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    # -- Lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close all database connections."""
        with self._lock:
            self.router.close_all()

    def __enter__(self) -> MemoryBridge:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"MemoryBridge(namespace={self.namespace!r})"
