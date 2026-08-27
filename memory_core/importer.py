"""v3.6 migration importer for Memory Core v2.

Imports data from an ``agent-memory-skill`` v3.6 database into the v2
schema.  Spec reference: §12.

Mapping:
    facts            → facts (add namespace, evidence_refs=[])
    recall_snippets  → episodes (role=assistant, origin=unknown)
    lessons          → lessons (add namespace)
    entities         → entities (add namespace)
    entity_relations → entity_relations (add namespace)
    procedural_rules → procedural_rules (add namespace)
    rule_conflicts   → rule_conflicts (add namespace)
    memory_meta      → memory_meta (add namespace)
    memory_audit     → memory_audit (add namespace)

Import is idempotent (content-hash IDs) and dry-runnable.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ids import make_id
from .router import StorageRouter
from .utils import utc_now_iso as _utc_now_iso

logger = logging.getLogger("memory_core.importer")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cursor.fetchone() is not None


def _column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


class ImportResult:
    """Collects import statistics."""

    def __init__(self) -> None:
        self.counts: Dict[str, int] = {}
        self.skipped: Dict[str, int] = {}
        self.errors: List[str] = []

    def add(self, table: str, count: int, skipped: int = 0) -> None:
        self.counts[table] = self.counts.get(table, 0) + count
        self.skipped[table] = self.skipped.get(table, 0) + skipped

    def to_dict(self) -> dict:
        return {
            "imported": self.counts,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def import_v3(
    router: StorageRouter,
    v3_path: str,
    namespace: str,
    *,
    dry_run: bool = False,
) -> ImportResult:
    """Import a v3.6 database into the v2 schema.

    Parameters
    ----------
    router:
        The v2 storage router.
    v3_path:
        Path to the v3.6 ``memory.db`` file.
    namespace:
        Target namespace for all imported data.
    dry_run:
        If ``True``, read and count but do not write.

    Returns
    -------
    ImportResult
        Statistics of what was (or would be) imported.
    """
    result = ImportResult()
    v3_db = Path(v3_path)
    if not v3_db.is_file():
        result.errors.append(f"v3 database not found: {v3_path}")
        return result

    v3_conn = sqlite3.connect(str(v3_db))
    v2_conn = router.connect(namespace)

    try:
        # Begin a single transaction for the entire import.
        v2_conn.execute("BEGIN IMMEDIATE")

        _import_facts(v3_conn, v2_conn, namespace, dry_run, result)
        _import_snippets_as_episodes(v3_conn, v2_conn, namespace, dry_run,
                                      result)
        _import_lessons(v3_conn, v2_conn, namespace, dry_run, result)
        _import_entities(v3_conn, v2_conn, namespace, dry_run, result)
        _import_entity_relations(v3_conn, v2_conn, namespace, dry_run, result)
        _import_procedural_rules(v3_conn, v2_conn, namespace, dry_run, result)
        _import_rule_conflicts(v3_conn, v2_conn, namespace, dry_run, result)
        _import_memory_meta(v3_conn, v2_conn, namespace, dry_run, result)
        _import_memory_audit(v3_conn, v2_conn, namespace, dry_run, result)

        if not dry_run:
            # Audit the import.
            v2_conn.cursor().execute(
                "INSERT INTO memory_audit "
                "(namespace, ts, op, source, accepted, reason, metadata) "
                "VALUES (?, ?, 'migrated_v3', 'observation', 1, "
                "'v3_import', ?)",
                (
                    namespace,
                    _utc_now_iso(),
                    json.dumps(result.to_dict(), ensure_ascii=False),
                ),
            )
            v2_conn.commit()
        else:
            v2_conn.rollback()
    except Exception as e:
        v2_conn.rollback()
        result.errors.append(f"Import failed, rolled back: {e}")
        logger.error("Import failed, rolled back: %s", e)
    finally:
        v3_conn.close()

    return result


# -- per-table importers ------------------------------------------------------

def _import_facts(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "facts"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, content, tags, source, confidence, authority_class, "
        "created_at, last_accessed, access_count, expires_at, superseded_by "
        "FROM facts"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        fid = row[0]
        # Idempotency: skip if already exists.
        v2_cursor.execute("SELECT 1 FROM facts WHERE id = ?", (fid,))
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO facts "
            "(id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed, "
            "access_count, expires_at, superseded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?)",
            (fid, ns) + row[1:],
        )
        imported += 1
    result.add("facts", imported, skipped)


def _import_snippets_as_episodes(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    """Migrate v3.6 ``recall_snippets`` to v2 ``episodes``."""
    if not _table_exists(v3, "recall_snippets"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, content, source, session_id, created_at, expires_at, "
        "metadata FROM recall_snippets"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        old_id = row[0]
        content = row[1]
        session_id = row[3]
        created_at = row[4]
        expires_at = row[5]
        old_meta = row[6]

        # Generate a v2 episode ID.
        ep_id = make_id("ep_", content, session_id or "", created_at)

        v2_cursor.execute("SELECT 1 FROM episodes WHERE id = ?", (ep_id,))
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue

        # Build metadata.
        meta = {"migrated": "snippet"}
        if old_meta:
            try:
                meta.update(json.loads(old_meta))
            except (json.JSONDecodeError, TypeError):
                pass

        v2_cursor.execute(
            "INSERT INTO episodes "
            "(id, namespace, session_id, role, origin, content, metadata, "
            "created_at, expires_at, consumed_by) "
            "VALUES (?, ?, ?, 'assistant', 'unknown', ?, ?, ?, ?, NULL)",
            (
                ep_id, ns, session_id, content,
                json.dumps(meta, ensure_ascii=False),
                created_at, expires_at,
            ),
        )
        imported += 1
    result.add("episodes_from_snippets", imported, skipped)


def _import_lessons(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "lessons"):
        return
    cursor = v3.cursor()
    columns = _column_names(v3, "lessons")
    select_cols = ", ".join(columns)
    cursor.execute(f"SELECT {select_cols} FROM lessons")
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        lid = row[0]
        v2_cursor.execute("SELECT 1 FROM lessons WHERE id = ?", (lid,))
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        # v3.6 lessons: id, action, context, outcome, insight, created_at,
        #               last_accessed, expires_at, applied_count
        v2_cursor.execute(
            "INSERT INTO lessons "
            "(id, namespace, action, context, outcome, insight, created_at, "
            "last_accessed, expires_at, applied_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (lid, ns) + row[1:],
        )
        imported += 1
    result.add("lessons", imported, skipped)


def _import_entities(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "entities"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, name, entity_type, attributes, first_seen, "
        "last_updated, last_accessed, expires_at, fact_ids FROM entities"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        eid = row[0]
        v2_cursor.execute("SELECT 1 FROM entities WHERE id = ?", (eid,))
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO entities "
            "(id, namespace, name, entity_type, attributes, first_seen, "
            "last_updated, last_accessed, expires_at, fact_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, ns) + row[1:],
        )
        imported += 1
    result.add("entities", imported, skipped)


def _import_entity_relations(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "entity_relations"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, from_id, predicate, to_id, attributes, created_at, "
        "last_accessed, expires_at FROM entity_relations"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        rid = row[0]
        v2_cursor.execute(
            "SELECT 1 FROM entity_relations WHERE id = ?", (rid,)
        )
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO entity_relations "
            "(id, namespace, from_id, predicate, to_id, attributes, "
            "created_at, last_accessed, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, ns) + row[1:],
        )
        imported += 1
    result.add("entity_relations", imported, skipped)


def _import_procedural_rules(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "procedural_rules"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, status, domain, trigger_json, effect_json, "
        "behavior_text, priority, tags, source, confidence, artifact_cost, "
        "evidence_fact_ids, rationale, created_at, approved_at, expires_at, "
        "review_due_at, rejected_at, rejection_reason, retired_at, "
        "superseded_by, previous_rule_id, last_matched_at, match_count "
        "FROM procedural_rules"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        rid = row[0]
        v2_cursor.execute(
            "SELECT 1 FROM procedural_rules WHERE id = ?", (rid,)
        )
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO procedural_rules "
            "(id, namespace, status, domain, trigger_json, effect_json, "
            "behavior_text, priority, tags, source, confidence, "
            "artifact_cost, evidence_fact_ids, rationale, created_at, "
            "approved_at, expires_at, review_due_at, rejected_at, "
            "rejection_reason, retired_at, superseded_by, "
            "previous_rule_id, last_matched_at, match_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, ns) + row[1:],
        )
        imported += 1
    result.add("procedural_rules", imported, skipped)


def _import_rule_conflicts(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "rule_conflicts"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT id, rule_a, rule_b, conflict_type, severity, dimension, "
        "reason, detected_at, resolved, resolved_at, resolution "
        "FROM rule_conflicts"
    )
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        cid = row[0]
        v2_cursor.execute(
            "SELECT 1 FROM rule_conflicts WHERE id = ?", (cid,)
        )
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO rule_conflicts "
            "(id, namespace, rule_a, rule_b, conflict_type, severity, "
            "dimension, reason, detected_at, resolved, resolved_at, "
            "resolution) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, ns) + row[1:],
        )
        imported += 1
    result.add("rule_conflicts", imported, skipped)


def _import_memory_meta(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    if not _table_exists(v3, "memory_meta"):
        return
    cursor = v3.cursor()
    cursor.execute("SELECT key, value FROM memory_meta")
    imported = 0
    skipped = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        key = row[0]
        v2_cursor.execute(
            "SELECT 1 FROM memory_meta WHERE key = ? AND namespace = ?",
            (key, ns),
        )
        if v2_cursor.fetchone():
            skipped += 1
            continue
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO memory_meta (key, namespace, value) "
            "VALUES (?, ?, ?)",
            (key, ns, row[1]),
        )
        imported += 1
    result.add("memory_meta", imported, skipped)


def _import_memory_audit(
    v3: sqlite3.Connection,
    v2: sqlite3.Connection,
    ns: str,
    dry_run: bool,
    result: ImportResult,
) -> None:
    """Import audit log verbatim (history is history)."""
    if not _table_exists(v3, "memory_audit"):
        return
    cursor = v3.cursor()
    cursor.execute(
        "SELECT ts, op, fact_id, content_hash, authority_class, source, "
        "accepted, reason, metadata FROM memory_audit "
        "ORDER BY id ASC"
    )
    imported = 0
    v2_cursor = v2.cursor()
    for row in cursor.fetchall():
        if dry_run:
            imported += 1
            continue
        v2_cursor.execute(
            "INSERT INTO memory_audit "
            "(namespace, ts, op, fact_id, content_hash, authority_class, "
            "source, accepted, reason, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ns,) + row,
        )
        imported += 1
    result.add("memory_audit", imported)
