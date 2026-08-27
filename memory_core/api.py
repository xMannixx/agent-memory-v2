"""High-Level API for Memory Core v2.

Provides simple one-call functions for common memory operations.
No need to create stores, routers, or configs manually.

Usage::

    from memory_core.api import memory_context, recall, add_episode

    # Get memory context for system prompt injection
    ctx = memory_context("my_agent", query="user preferences")

    # Search facts
    facts = recall("my_agent", "Python programming")

    # Record an episode
    add_episode("my_agent", "User likes Rust", role="user")

    # Full conversation turn
    add_conversation_turn("my_agent", "Was ist mein Beruf?", "Du bist Entwickler.")
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .config import load_config, Config
from .episodes import EpisodeStore
from .facts import FactStore
from .injection import get_injection_block
from .narratives import NarrativeStore
from .router import StorageRouter
from .schema import init_schema


def _make_stores(
    namespace: str,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
):
    """Create temporary stores for a one-shot operation."""
    if config is None:
        if data_dir is not None:
            old = os.environ.get("MEMORY_CORE_STORAGE_DATA_DIR")
            os.environ["MEMORY_CORE_STORAGE_DATA_DIR"] = data_dir
            try:
                config = load_config()
            finally:
                if old is None:
                    os.environ.pop("MEMORY_CORE_STORAGE_DATA_DIR", None)
                else:
                    os.environ["MEMORY_CORE_STORAGE_DATA_DIR"] = old
        else:
            config = load_config()

    router = StorageRouter(config)
    conn = router.connect(namespace)
    init_schema(conn)

    return router, config


def memory_context(
    namespace: str,
    query: Optional[str] = None,
    *,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
    max_chars: Optional[int] = None,
) -> str:
    """Get memory context for system prompt injection.

    Returns a formatted ``# Memory Context`` block with narrative and
    relevant facts, ready to paste into a system prompt.

    Parameters
    ----------
    namespace : str
        Memory namespace (e.g. ``"agent_main"``).
    query : str or None
        Optional query for relevance-based fact retrieval.
        If ``None``, returns narrative + recent facts.
    data_dir : str or None
        Override data directory. Defaults to ``~/.memory-core``.
    config : Config or None
        Override full configuration.
    max_chars : int or None
        Max characters. Defaults to config value.

    Returns
    -------
    str
        Formatted memory context block, or empty string.

    Example
    -------
    >>> ctx = memory_context("my_agent", query="Beruf Arbeit")
    >>> print(ctx)
    # Memory Context
    User is a developer at ACME Corp.

    Relevant Facts:
    - User works as Schichtleiter
    - User lives in Rielasingen
    """
    router, cfg = _make_stores(namespace, data_dir, config)
    try:
        narratives = NarrativeStore(router, cfg)
        facts = FactStore(router)

        block = get_injection_block(namespace, narratives, facts, cfg)

        if max_chars and len(block) > max_chars:
            block = block[:max_chars] + "..."

        return block
    finally:
        router.close_all()


def recall(
    namespace: str,
    query: str,
    *,
    limit: int = 10,
    authority_class: Optional[str] = None,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """Search memory and return facts as dicts.

    Parameters
    ----------
    namespace : str
        Memory namespace.
    query : str
        Search query (FTS5).
    limit : int
        Max results.
    authority_class : str or None
        Filter by lane (e.g. ``"identity"``, ``"preference"``).
    data_dir : str or None
        Override data directory.
    config : Config or None
        Override full configuration.

    Returns
    -------
    list[dict]
        List of fact dictionaries.

    Example
    -------
    >>> facts = recall("my_agent", "Python")
    >>> for f in facts:
    ...     print(f["content"])
    User likes Python programming
    """
    router, cfg = _make_stores(namespace, data_dir, config)
    try:
        facts = FactStore(router)
        results = facts.recall(
            namespace,
            query,
            limit=limit,
            authority_class=authority_class,
        )
        return [f.to_dict() for f in results]
    finally:
        router.close_all()


def add_episode(
    namespace: str,
    content: str,
    role: str = "user",
    *,
    origin: str = "unknown",
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
) -> str:
    """Record a single episode.

    Parameters
    ----------
    namespace : str
        Memory namespace.
    content : str
        Episode content.
    role : str
        One of ``user``, ``assistant``, ``tool``, ``system``.
    origin : str
        Origin vocabulary.
    session_id : str or None
        Optional session ID.
    metadata : dict or None
        Optional metadata.
    data_dir : str or None
        Override data directory.
    config : Config or None
        Override full configuration.

    Returns
    -------
    str
        Episode ID.

    Example
    -------
    >>> ep_id = add_episode("my_agent", "User likes Python", role="user")
    """
    router, cfg = _make_stores(namespace, data_dir, config)
    try:
        episodes = EpisodeStore(router)
        return episodes.add(
            namespace,
            content,
            role,
            origin=origin,
            session_id=session_id,
            metadata=metadata or {},
        )
    finally:
        router.close_all()


def add_conversation_turn(
    namespace: str,
    user_message: str,
    assistant_message: str,
    *,
    session_id: Optional[str] = None,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
) -> List[str]:
    """Record a full user+assistant turn as two episodes.

    Returns
    -------
    list[str]
        The two episode IDs ``[user_ep_id, assistant_ep_id]``.

    Example
    -------
    >>> ids = add_conversation_turn("my_agent", "Hallo", "Hallo!")
    """
    ep1 = add_episode(
        namespace, user_message, "user",
        origin="trusted_user", session_id=session_id,
        data_dir=data_dir, config=config,
    )
    ep2 = add_episode(
        namespace, assistant_message, "assistant",
        origin="unknown", session_id=session_id,
        data_dir=data_dir, config=config,
    )
    return [ep1, ep2]


def get_facts(
    namespace: str,
    *,
    authority_class: Optional[str] = None,
    limit: int = 50,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """List all active facts.

    Returns
    -------
    list[dict]
        List of fact dictionaries.

    Example
    -------
    >>> facts = get_facts("my_agent", authority_class="identity")
    """
    router, cfg = _make_stores(namespace, data_dir, config)
    try:
        facts = FactStore(router)
        results = facts.list_facts(
            namespace,
            authority_class=authority_class,
            limit=limit,
        )
        return [f.to_dict() for f in results]
    finally:
        router.close_all()


def get_stats(
    namespace: str,
    *,
    data_dir: Optional[str] = None,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Return memory statistics.

    Returns
    -------
    dict
        Statistics with ``active`` count and ``by_lane`` breakdown.

    Example
    -------
    >>> stats = get_stats("my_agent")
    >>> print(stats)
    {'active': 5, 'by_lane': {'identity': 2, 'preference': 3}}
    """
    router, cfg = _make_stores(namespace, data_dir, config)
    try:
        facts = FactStore(router)
        return facts.stats(namespace)
    finally:
        router.close_all()
