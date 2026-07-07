"""SQLite schema definitions and migrations for Memory Core v2.

All statements use ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS`` to satisfy INV-11 (additive migrations only).  Schema is derived
from the master specification §4.

Carried-over tables from v3.6 gain a ``namespace`` column.
"""

from __future__ import annotations

import sqlite3


# -- DDL statements -----------------------------------------------------------

_EPISODES_DDL = """\
CREATE TABLE IF NOT EXISTS episodes (
    id            TEXT PRIMARY KEY,
    namespace     TEXT NOT NULL,
    session_id    TEXT,
    role          TEXT NOT NULL,
    origin        TEXT NOT NULL,
    content       TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    expires_at    TEXT,
    consumed_by   TEXT
);
"""

_FACTS_DDL = """\
CREATE TABLE IF NOT EXISTS facts (
    id              TEXT PRIMARY KEY,
    namespace       TEXT NOT NULL,
    content         TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL,
    confidence      REAL NOT NULL,
    authority_class TEXT NOT NULL DEFAULT 'evidence',
    evidence_refs   TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    last_accessed   TEXT NOT NULL,
    access_count    INTEGER NOT NULL DEFAULT 1,
    expires_at      TEXT,
    superseded_by   TEXT
);
"""

_NARRATIVES_DDL = """\
CREATE TABLE IF NOT EXISTS narratives (
    id          TEXT PRIMARY KEY,
    namespace   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    UNIQUE(namespace, version)
);
"""

_PROPOSAL_QUEUE_DDL = """\
CREATE TABLE IF NOT EXISTS proposal_queue (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    namespace     TEXT NOT NULL,
    proposal_type TEXT NOT NULL,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL,
    gate_report   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    decided_at    TEXT,
    decided_by    TEXT
);
"""

# Carried-over tables from v3.6 with namespace column added.

_ENTITIES_DDL = """\
CREATE TABLE IF NOT EXISTS entities (
    id           TEXT PRIMARY KEY,
    namespace    TEXT NOT NULL,
    name         TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    attributes   TEXT,
    first_seen   TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    last_accessed TEXT,
    expires_at   TEXT,
    fact_ids     TEXT
);
"""

_ENTITY_RELATIONS_DDL = """\
CREATE TABLE IF NOT EXISTS entity_relations (
    id           TEXT PRIMARY KEY,
    namespace    TEXT NOT NULL,
    from_id      TEXT NOT NULL,
    predicate    TEXT NOT NULL,
    to_id        TEXT NOT NULL,
    attributes   TEXT,
    created_at   TEXT NOT NULL,
    last_accessed TEXT,
    expires_at   TEXT
);
"""

_LESSONS_DDL = """\
CREATE TABLE IF NOT EXISTS lessons (
    id            TEXT PRIMARY KEY,
    namespace     TEXT NOT NULL,
    action        TEXT NOT NULL,
    context       TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    insight       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_accessed TEXT,
    expires_at    TEXT,
    applied_count INTEGER DEFAULT 0
);
"""

_FACT_CONFLICTS_DDL = """\
CREATE TABLE IF NOT EXISTS fact_conflicts (
    id          TEXT PRIMARY KEY,
    namespace   TEXT NOT NULL,
    lane        TEXT NOT NULL,
    tags        TEXT,
    fact_a      TEXT NOT NULL,
    fact_b      TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0
);
"""

_PROCEDURAL_RULES_DDL = """\
CREATE TABLE IF NOT EXISTS procedural_rules (
    id                TEXT PRIMARY KEY,
    namespace         TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    domain            TEXT NOT NULL,
    trigger_json      TEXT NOT NULL,
    effect_json       TEXT NOT NULL,
    behavior_text     TEXT NOT NULL,
    priority          INTEGER DEFAULT 50,
    tags              TEXT,
    source            TEXT NOT NULL DEFAULT 'observation',
    confidence        REAL DEFAULT 0.5,
    artifact_cost     INTEGER DEFAULT 0,
    evidence_fact_ids TEXT,
    rationale         TEXT,
    created_at        TEXT NOT NULL,
    approved_at       TEXT,
    expires_at        TEXT,
    review_due_at     TEXT,
    rejected_at       TEXT,
    rejection_reason  TEXT,
    retired_at        TEXT,
    superseded_by     TEXT,
    previous_rule_id  TEXT,
    last_matched_at   TEXT,
    match_count       INTEGER DEFAULT 0
);
"""

_RULE_CONFLICTS_DDL = """\
CREATE TABLE IF NOT EXISTS rule_conflicts (
    id            TEXT PRIMARY KEY,
    namespace     TEXT NOT NULL,
    rule_a        TEXT NOT NULL,
    rule_b        TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'warning',
    dimension     TEXT,
    reason        TEXT NOT NULL,
    detected_at   TEXT NOT NULL,
    resolved      INTEGER NOT NULL DEFAULT 0,
    resolved_at   TEXT,
    resolution    TEXT
);
"""

_MEMORY_META_DDL = """\
CREATE TABLE IF NOT EXISTS memory_meta (
    key       TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',
    value     TEXT,
    PRIMARY KEY (key, namespace)
);
"""

_MEMORY_AUDIT_DDL = """\
CREATE TABLE IF NOT EXISTS memory_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace       TEXT NOT NULL,
    ts              TEXT NOT NULL,
    op              TEXT NOT NULL,
    fact_id         TEXT,
    content_hash    TEXT,
    authority_class TEXT,
    source          TEXT,
    accepted        INTEGER NOT NULL DEFAULT 1,
    reason          TEXT,
    metadata        TEXT
);
"""

# -- FTS5 virtual tables -----------------------------------------------------

_FACTS_FTS_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
USING fts5(content, tags, tokenize='porter');
"""

_EPISODES_FTS_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
USING fts5(content, tokenize='porter');
"""

# -- Indexes ------------------------------------------------------------------

_INDEXES_DDL = """\
CREATE INDEX IF NOT EXISTS idx_episodes_ns_created
    ON episodes(namespace, created_at);
CREATE INDEX IF NOT EXISTS idx_episodes_unconsumed
    ON episodes(namespace, consumed_by)
    WHERE consumed_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_episodes_expires
    ON episodes(expires_at);

CREATE INDEX IF NOT EXISTS idx_facts_ns_class_super
    ON facts(namespace, authority_class, superseded_by);
CREATE INDEX IF NOT EXISTS idx_facts_expires
    ON facts(expires_at);
CREATE INDEX IF NOT EXISTS idx_facts_last_accessed
    ON facts(last_accessed);

CREATE INDEX IF NOT EXISTS idx_narratives_ns_version
    ON narratives(namespace, version);

CREATE INDEX IF NOT EXISTS idx_proposal_queue_status
    ON proposal_queue(status);
CREATE INDEX IF NOT EXISTS idx_proposal_queue_ns_status
    ON proposal_queue(namespace, status);

CREATE INDEX IF NOT EXISTS idx_lessons_ns_outcome_time
    ON lessons(namespace, outcome, created_at);
CREATE INDEX IF NOT EXISTS idx_lessons_expires
    ON lessons(expires_at);

CREATE INDEX IF NOT EXISTS idx_entities_ns_type_name
    ON entities(namespace, entity_type, name);
CREATE INDEX IF NOT EXISTS idx_entities_expires
    ON entities(expires_at);

CREATE INDEX IF NOT EXISTS idx_fact_conflicts_ns_resolved
    ON fact_conflicts(namespace, resolved);

CREATE INDEX IF NOT EXISTS idx_entity_relations_ns_from
    ON entity_relations(namespace, from_id);
CREATE INDEX IF NOT EXISTS idx_entity_relations_ns_to
    ON entity_relations(namespace, to_id);

CREATE INDEX IF NOT EXISTS idx_audit_ns_ts
    ON memory_audit(namespace, ts);
CREATE INDEX IF NOT EXISTS idx_audit_op
    ON memory_audit(op);

CREATE INDEX IF NOT EXISTS idx_procedural_ns_status
    ON procedural_rules(namespace, status);
CREATE INDEX IF NOT EXISTS idx_procedural_ns_domain
    ON procedural_rules(namespace, domain);
CREATE INDEX IF NOT EXISTS idx_procedural_expires
    ON procedural_rules(expires_at);

CREATE INDEX IF NOT EXISTS idx_rule_conflicts_ns_resolved
    ON rule_conflicts(namespace, resolved);
"""

# -- FTS triggers (v3.6 pattern) ----------------------------------------------

_FACTS_FTS_TRIGGERS = """\
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, content, tags)
    VALUES (new.rowid, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    DELETE FROM facts_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    DELETE FROM facts_fts WHERE rowid = old.rowid;
    INSERT INTO facts_fts(rowid, content, tags)
    VALUES (new.rowid, new.content, new.tags);
END;
"""

_EPISODES_FTS_TRIGGERS = """\
CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    DELETE FROM episodes_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
    DELETE FROM episodes_fts WHERE rowid = old.rowid;
    INSERT INTO episodes_fts(rowid, content)
    VALUES (new.rowid, new.content);
END;
"""


# -- Public API ---------------------------------------------------------------

def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, FTS triggers.  Idempotent.

    Enables WAL mode for file-backed databases.
    """
    cursor = conn.cursor()

    # Core tables.
    cursor.execute(_EPISODES_DDL)
    cursor.execute(_FACTS_DDL)
    cursor.execute(_NARRATIVES_DDL)
    cursor.execute(_PROPOSAL_QUEUE_DDL)

    # Carried-over tables.
    cursor.execute(_ENTITIES_DDL)
    cursor.execute(_ENTITY_RELATIONS_DDL)
    cursor.execute(_LESSONS_DDL)
    cursor.execute(_FACT_CONFLICTS_DDL)
    cursor.execute(_PROCEDURAL_RULES_DDL)
    cursor.execute(_RULE_CONFLICTS_DDL)
    cursor.execute(_MEMORY_META_DDL)
    cursor.execute(_MEMORY_AUDIT_DDL)

    # FTS virtual tables.
    cursor.execute(_FACTS_FTS_DDL)
    cursor.execute(_EPISODES_FTS_DDL)

    # Cleanup orphaned FTS rows (safety net after unclean shutdown).
    cursor.execute(
        "DELETE FROM facts_fts WHERE rowid NOT IN (SELECT rowid FROM facts)"
    )
    cursor.execute(
        "DELETE FROM episodes_fts "
        "WHERE rowid NOT IN (SELECT rowid FROM episodes)"
    )

    # FTS triggers.
    cursor.executescript(_FACTS_FTS_TRIGGERS)
    cursor.executescript(_EPISODES_FTS_TRIGGERS)

    # Indexes.
    cursor.executescript(_INDEXES_DDL)

    # WAL mode for file-backed DBs.
    _enable_wal(cursor)

    conn.commit()


def _enable_wal(cursor: sqlite3.Cursor) -> None:
    """Enable WAL journal mode if the database is file-backed."""
    try:
        cursor.execute("PRAGMA database_list")
        for row in cursor.fetchall():
            # row[2] is the file path; empty for :memory:
            if row[2]:
                cursor.execute("PRAGMA journal_mode=WAL")
                return
    except Exception:
        pass


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check whether a table exists in the database."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None
