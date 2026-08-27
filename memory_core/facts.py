"""Fact read API for Memory Core v2 (B1 scope: read-only).

Direct fact writes are handled by:
    - The v3.6 migration importer (``importer.py``)
    - The gate pipeline (B2)
    - Explicit human CLI commands (B2)

The retrieval stack (FTS5 query builder, text_norm, synonyms,
score-based ranking) is ported 1:1 from v3.6.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Fact, row_to_fact
from .router import StorageRouter
from .utils import utc_now_iso

logger = logging.getLogger("memory_core.facts")

# Column order for SELECT statements (must match row_to_fact).
_FACT_COLUMNS = (
    "id, namespace, content, tags, source, confidence, authority_class, "
    "evidence_refs, created_at, last_accessed, access_count, expires_at, "
    "superseded_by"
)

# Authority Lane policies (carried from v3.6, spec §4.2 / §6.3).
AUTHORITY_POLICY = {
    "identity": {
        "ttl_days": None,  # never expires
        "min_confidence": 0.9,
        "allowed_sources": {"observation", "conversation"},
        "single_valued": True,
        "content_max_chars": 500,
    },
    "preference": {
        "ttl_days": 14,
        "min_confidence": 0.3,
        "allowed_sources": {"observation", "conversation"},
        "single_valued": False,
        "content_max_chars": 1000,
    },
    "evidence": {
        "ttl_days": 60,
        "min_confidence": 0.5,
        "allowed_sources": {
            "observation", "conversation", "inference", "tool", "external",
        },
        "single_valued": False,
        "content_max_chars": 2000,
    },
    "authorization": {
        "ttl_days": 90,
        "min_confidence": 0.9,
        "allowed_sources": {"observation"},
        "single_valued": True,
        "content_max_chars": 500,
    },
    "procedural": {
        "ttl_days": 30,
        "min_confidence": 0.5,
        "allowed_sources": {"observation"},
        "single_valued": False,
        "content_max_chars": 1500,
    },
}

# Stopwords for query processing.
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "das", "der", "die", "for", "how", "is",
    "ist", "mit", "of", "oder", "or", "the", "to", "und", "was", "what",
    "wie", "with",
}

# Try to load text_norm (German-aware scoring layer).
try:
    from .text_norm import (
        normalize as _norm_normalize,
        query_terms as _norm_query_terms,
    )
except ImportError:
    _norm_normalize = None
    _norm_query_terms = None

# Try to load synonyms.
_SYNONYMS: Dict[str, List[str]] = {}
try:
    _syn_path = Path(__file__).parent / "synonyms.json"
    if _syn_path.is_file():
        with open(_syn_path, encoding="utf-8") as fh:
            _SYNONYMS = json.load(fh)
except Exception:
    pass


class FactStore:
    """Read-only fact API for B1.

    Parameters
    ----------
    router:
        The storage router to use for connections.
    """

    def __init__(self, router: StorageRouter) -> None:
        self._router = router

    # -- query ----------------------------------------------------------------

    def recall(
        self,
        namespace: str,
        query: str,
        *,
        limit: int = 10,
        authority_class: Optional[str] = None,
        include_shared: bool = False,
    ) -> List[Fact]:
        """Search facts by FTS5 query, ranked by relevance.

        The German-aware scoring layer is applied when ``text_norm`` is
        available.
        """
        started_at = time.perf_counter()
        conns = self._router.connect_read(
            namespace, include_shared=include_shared
        )
        fts_query = self._smart_fts_query(query)
        if not fts_query:
            return []

        all_facts: List[Fact] = []
        seen_ids: set = set()

        for conn in conns:
            cursor = conn.cursor()
            sql = (
                f"SELECT {_FACT_COLUMNS} FROM facts "
                "WHERE namespace = ? AND superseded_by IS NULL "
                "AND rowid IN ("
                "    SELECT rowid FROM facts_fts WHERE facts_fts MATCH ?"
                ")"
            )
            params: list = [namespace if conn == conns[0] else "shared",
                            fts_query]

            if authority_class:
                sql += " AND authority_class = ?"
                params.append(authority_class)

            sql += " ORDER BY last_accessed DESC LIMIT ?"
            params.append(limit * 3)  # over-fetch for ranking

            cursor.execute(sql, params)
            for row in cursor.fetchall():
                fact = row_to_fact(row)
                if fact.id not in seen_ids:
                    seen_ids.add(fact.id)
                    all_facts.append(fact)

        # Rank by relevance.
        ranked = self._rank_relevant(all_facts, query)[:limit]

        # Touch accessed facts (sliding TTL).
        self._touch_facts(namespace, [f.id for f in ranked])

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.debug("recall(%r) returned %d facts in %.1fms",
                      query, len(ranked), elapsed_ms)
        return ranked

    def recall_by_authority(
        self,
        namespace: str,
        authority_class: str,
        *,
        limit: int = 50,
        include_shared: bool = False,
    ) -> List[Fact]:
        """Return facts for a specific authority lane, most recently
        accessed first."""
        conns = self._router.connect_read(
            namespace, include_shared=include_shared
        )
        all_facts: List[Fact] = []
        seen_ids: set = set()

        for conn in conns:
            ns = namespace if conn == conns[0] else "shared"
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {_FACT_COLUMNS} FROM facts "
                "WHERE namespace = ? AND authority_class = ? "
                "AND superseded_by IS NULL "
                "ORDER BY last_accessed DESC LIMIT ?",
                (ns, authority_class, limit),
            )
            for row in cursor.fetchall():
                fact = row_to_fact(row)
                if fact.id not in seen_ids:
                    seen_ids.add(fact.id)
                    all_facts.append(fact)

        result = all_facts[:limit]
        self._touch_facts(namespace, [f.id for f in result])
        return result

    def get_fact(
        self,
        namespace: str,
        fact_id: str,
    ) -> Optional[Fact]:
        """Return a single fact by ID, or ``None``."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE id = ?",
            (fact_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        fact = row_to_fact(row)
        self._touch_facts(namespace, [fact.id])
        return fact

    def list_facts(
        self,
        namespace: str,
        *,
        tags: Optional[List[str]] = None,
        authority_class: Optional[str] = None,
        limit: int = 50,
    ) -> List[Fact]:
        """List facts, optionally filtered by tags or lane."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()

        sql = (
            f"SELECT {_FACT_COLUMNS} FROM facts "
            "WHERE namespace = ? AND superseded_by IS NULL"
        )
        params: list = [namespace]

        if authority_class:
            sql += " AND authority_class = ?"
            params.append(authority_class)

        sql += " ORDER BY last_accessed DESC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, params)
        facts = [row_to_fact(row) for row in cursor.fetchall()]

        # Post-filter by tags if requested.
        if tags:
            tag_set = set(tags)
            facts = [f for f in facts if tag_set & set(f.tags)]

        return facts

    def stats(self, namespace: str) -> Dict[str, Any]:
        """Return fact statistics for *namespace*."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM facts "
            "WHERE namespace = ? AND superseded_by IS NULL",
            (namespace,),
        )
        active = cursor.fetchone()[0]

        cursor.execute(
            "SELECT authority_class, COUNT(*) FROM facts "
            "WHERE namespace = ? AND superseded_by IS NULL "
            "GROUP BY authority_class",
            (namespace,),
        )
        by_lane = dict(cursor.fetchall())

        return {
            "active": active,
            "by_lane": by_lane,
        }

    # -- write (used by consolidator and queue) -------------------------------

    def write_fact(self, namespace: str, proposal: Dict[str, Any]) -> str:
        """Write a fact from a gate-approved proposal. Returns the fact ID."""
        from .ids import fact_id
        lane = proposal["lane"]
        content = proposal["content"]
        fid = fact_id(content, lane)
        now = utc_now_iso()

        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO facts "
            "(id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
            (
                fid, namespace, content,
                proposal.get("source", "inference"),
                proposal.get("confidence", 1.0),
                lane,
                json.dumps(proposal.get("evidence_refs", [])),
                now, now,
            ),
        )
        conn.commit()
        return fid

    def supersede_fact(self, namespace: str, proposal: Dict[str, Any]) -> Optional[str]:
        """Supersede an existing fact. Returns the new fact ID, or None if old fact not found."""
        from .ids import fact_id as _fact_id
        old_id = proposal["old_fact_id"]
        content = proposal["content"]

        conn = self._router.connect(namespace)
        cursor = conn.cursor()

        cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
        row = cursor.fetchone()
        if not row:
            return None

        lane = row[0]
        new_fid = _fact_id(content, lane)
        now = utc_now_iso()

        cursor.execute(
            "INSERT OR IGNORE INTO facts "
            "(id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
            (
                new_fid, namespace, content,
                proposal.get("source", "inference"), 1.0, lane,
                json.dumps(proposal.get("evidence_refs", [])),
                now, now,
            ),
        )
        cursor.execute(
            "UPDATE facts SET superseded_by = ? WHERE id = ?",
            (new_fid, old_id),
        )
        conn.commit()
        return new_fid

    # -- sliding TTL ----------------------------------------------------------

    def _touch_facts(self, namespace: str, fact_ids: List[str]) -> None:
        """Refresh ``last_accessed`` and extend ``expires_at`` for accessed
        facts (sliding TTL, spec §2 / v3.6 architecture).

        Uses a single batched UPDATE instead of per-fact queries.
        """
        if not fact_ids:
            return
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Batch-read lanes for all facts in one query.
        placeholders = ",".join("?" for _ in fact_ids)
        cursor.execute(
            f"SELECT id, authority_class FROM facts WHERE id IN ({placeholders})",
            fact_ids,
        )
        lane_map: Dict[str, str] = {row[0]: row[1] for row in cursor.fetchall()}

        # Group facts by lane for batch updates.
        by_lane: Dict[str, List[str]] = {}
        for fid, lane in lane_map.items():
            by_lane.setdefault(lane, []).append(fid)

        for lane, ids in by_lane.items():
            policy = AUTHORITY_POLICY.get(lane, AUTHORITY_POLICY["evidence"])
            ttl_days = policy.get("ttl_days")
            new_expires: Optional[str] = None
            if ttl_days is not None:
                new_expires = (now + timedelta(days=ttl_days)).isoformat()

            ph = ",".join("?" for _ in ids)
            cursor.execute(
                f"UPDATE facts SET last_accessed = ?, "
                f"access_count = access_count + 1, "
                f"expires_at = COALESCE(?, expires_at) "
                f"WHERE id IN ({ph})",
                [now_iso, new_expires] + ids,
            )
        conn.commit()

    # -- FTS query builder (v3.6 pattern) -------------------------------------

    def _smart_fts_query(self, query: str) -> str:
        """Build a German-aware FTS5 query with synonym expansion.

        Uses unquoted token-prefix terms (``server*``) so compound German
        words are matched.  Synonyms are expanded from ``synonyms.json``.
        """
        terms = self._query_terms(query)
        if not terms:
            return ""

        # Expand with synonyms.
        expanded = list(terms)
        for term in terms:
            lower = term.lower()
            # Direct synonym lookup.
            if lower in _SYNONYMS:
                expanded.extend(_SYNONYMS[lower])
            # Reverse lookup.
            for key, values in _SYNONYMS.items():
                if lower in [v.lower() for v in values]:
                    expanded.append(key)
                    expanded.extend(v for v in values if v.lower() != lower)

        # Deduplicate while preserving order.
        seen: set = set()
        unique = []
        for t in expanded:
            tl = t.lower()
            if tl not in seen:
                seen.add(tl)
                unique.append(tl)

        return " OR ".join(f"{t}*" for t in unique)

    def _query_terms(self, text: str) -> List[str]:
        """Extract useful query terms."""
        return [
            t.lower() for t in re.findall(r"\w+", text)
            if len(t) >= 3 and t.lower() not in _QUERY_STOPWORDS
        ]

    def _rank_relevant(
        self, facts: List[Fact], query: str
    ) -> List[Fact]:
        """Rank facts by normalized term overlap (v3.6 scoring layer)."""
        if _norm_query_terms is None or _norm_normalize is None:
            return facts

        query_norm = {
            _norm_normalize(t) for t in _norm_query_terms(query)
        }
        if not query_norm:
            return facts

        scored = []
        for i, fact in enumerate(facts):
            fact_norm = {
                _norm_normalize(t) for t in _norm_query_terms(fact.content)
            }
            score = float(len(query_norm & fact_norm))
            scored.append((score, i, fact))

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [f for _, _, f in scored]
