"""Tests for the v3.6 migration importer."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import Config, StorageConfig
from src.router import StorageRouter
from src.importer import import_v3
from src.schema import table_exists


def _create_v3_db(path: Path) -> sqlite3.Connection:
    """Create a minimal v3.6-style database for testing."""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()

    # facts table (v3.6 schema — no namespace, no evidence_refs)
    cur.execute("""
        CREATE TABLE facts (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            tags TEXT,
            source TEXT DEFAULT 'conversation',
            confidence REAL DEFAULT 1.0,
            authority_class TEXT DEFAULT 'evidence',
            created_at TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count INTEGER DEFAULT 1,
            expires_at TEXT,
            superseded_by TEXT
        )
    """)

    # recall_snippets (v3.6 — to be migrated to episodes)
    cur.execute("""
        CREATE TABLE recall_snippets (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'conversation',
            session_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            metadata TEXT
        )
    """)

    # lessons
    cur.execute("""
        CREATE TABLE lessons (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            context TEXT NOT NULL,
            outcome TEXT NOT NULL,
            insight TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_accessed TEXT,
            expires_at TEXT,
            applied_count INTEGER DEFAULT 0
        )
    """)

    # entities
    cur.execute("""
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            attributes TEXT,
            first_seen TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            last_accessed TEXT,
            expires_at TEXT,
            fact_ids TEXT
        )
    """)

    # entity_relations
    cur.execute("""
        CREATE TABLE entity_relations (
            id TEXT PRIMARY KEY,
            from_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            to_id TEXT NOT NULL,
            attributes TEXT,
            created_at TEXT NOT NULL,
            last_accessed TEXT,
            expires_at TEXT
        )
    """)

    # memory_meta
    cur.execute("""
        CREATE TABLE memory_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # memory_audit
    cur.execute("""
        CREATE TABLE memory_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            op TEXT NOT NULL,
            fact_id TEXT,
            content_hash TEXT,
            authority_class TEXT,
            source TEXT,
            accepted INTEGER NOT NULL DEFAULT 1,
            reason TEXT,
            metadata TEXT
        )
    """)

    # Insert sample data.
    cur.execute(
        "INSERT INTO facts VALUES "
        "('f_001', 'User name is Alex', '[]', 'observation', 1.0, "
        "'identity', '2026-01-01T00:00:00', '2026-01-01T00:00:00', "
        "1, NULL, NULL)"
    )
    cur.execute(
        "INSERT INTO facts VALUES "
        "('f_002', 'VPS runs Ubuntu', '[\"vps\"]', 'conversation', 0.8, "
        "'evidence', '2026-02-01T00:00:00', '2026-02-01T00:00:00', "
        "3, '2026-08-01T00:00:00', NULL)"
    )
    cur.execute(
        "INSERT INTO recall_snippets VALUES "
        "('s_001', 'Discussed Nextcloud setup', 'conversation', "
        "'ses_abc', '2026-03-01T00:00:00', '2026-06-01T00:00:00', NULL)"
    )
    cur.execute(
        "INSERT INTO lessons VALUES "
        "('l_001', 'Deployed without fallback', 'hermes-setup', "
        "'negative', 'Always configure a fallback', "
        "'2026-01-15T00:00:00', NULL, NULL, 0)"
    )
    cur.execute(
        "INSERT INTO entities VALUES "
        "('e_001', 'Alex', 'person', '{\"lang\": \"de\"}', "
        "'2026-01-01T00:00:00', '2026-01-01T00:00:00', NULL, NULL, "
        "'[\"f_001\"]')"
    )
    cur.execute(
        "INSERT INTO entity_relations VALUES "
        "('rel_001', 'e_001', 'arbeitet_bei', 'e_002', NULL, "
        "'2026-01-01T00:00:00', NULL, NULL)"
    )
    cur.execute(
        "INSERT INTO memory_meta VALUES ('last_session', '2026-06-01')"
    )
    cur.execute(
        "INSERT INTO memory_audit "
        "(ts, op, fact_id, content_hash, authority_class, source, "
        "accepted, reason, metadata) "
        "VALUES ('2026-01-01', 'write', 'f_001', 'abc', 'identity', "
        "'observation', 1, NULL, NULL)"
    )

    conn.commit()
    return conn


@pytest.fixture
def v3_db(tmp_path):
    """Path to a v3.6-style test database."""
    path = tmp_path / "v3_memory.db"
    conn = _create_v3_db(path)
    conn.close()
    return path


@pytest.fixture
def v2_router(tmp_path):
    """A v2 StorageRouter pointing to a temp directory."""
    config = Config(storage=StorageConfig(
        mode="single", data_dir=str(tmp_path / "v2"),
    ))
    router = StorageRouter(config)
    yield router
    router.close_all()


class TestImportFacts:
    def test_facts_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("facts", 0) == 2

    def test_facts_have_namespace(self, v3_db, v2_router):
        import_v3(v2_router, str(v3_db), "test_ns")
        conn = v2_router.connect("test_ns")
        cur = conn.cursor()
        cur.execute("SELECT namespace FROM facts WHERE id = 'f_001'")
        assert cur.fetchone()[0] == "test_ns"

    def test_facts_have_empty_evidence_refs(self, v3_db, v2_router):
        import_v3(v2_router, str(v3_db), "test_ns")
        conn = v2_router.connect("test_ns")
        cur = conn.cursor()
        cur.execute("SELECT evidence_refs FROM facts WHERE id = 'f_001'")
        assert json.loads(cur.fetchone()[0]) == []


class TestImportSnippetsAsEpisodes:
    def test_snippets_become_episodes(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("episodes_from_snippets", 0) == 1

    def test_episode_has_correct_role_origin(self, v3_db, v2_router):
        import_v3(v2_router, str(v3_db), "test_ns")
        conn = v2_router.connect("test_ns")
        cur = conn.cursor()
        cur.execute("SELECT role, origin FROM episodes LIMIT 1")
        row = cur.fetchone()
        assert row[0] == "assistant"
        assert row[1] == "unknown"

    def test_episode_metadata_marked_migrated(self, v3_db, v2_router):
        import_v3(v2_router, str(v3_db), "test_ns")
        conn = v2_router.connect("test_ns")
        cur = conn.cursor()
        cur.execute("SELECT metadata FROM episodes LIMIT 1")
        meta = json.loads(cur.fetchone()[0])
        assert meta.get("migrated") == "snippet"


class TestImportOtherTables:
    def test_lessons_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("lessons", 0) == 1

    def test_entities_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("entities", 0) == 1

    def test_entity_relations_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("entity_relations", 0) == 1

    def test_memory_meta_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("memory_meta", 0) == 1

    def test_memory_audit_imported(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns")
        assert result.counts.get("memory_audit", 0) >= 1


class TestIdempotency:
    def test_reimport_skips_existing(self, v3_db, v2_router):
        result1 = import_v3(v2_router, str(v3_db), "test_ns")
        result2 = import_v3(v2_router, str(v3_db), "test_ns")
        # Second run should skip everything.
        assert result2.skipped.get("facts", 0) == 2
        assert result2.counts.get("facts", 0) == 0


class TestDryRun:
    def test_dry_run_no_writes(self, v3_db, v2_router):
        result = import_v3(v2_router, str(v3_db), "test_ns", dry_run=True)
        assert result.counts.get("facts", 0) == 2
        # Verify nothing was actually written.
        conn = v2_router.connect("test_ns")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM facts")
        assert cur.fetchone()[0] == 0


class TestMissingDb:
    def test_missing_db_reports_error(self, v2_router):
        result = import_v3(v2_router, "/nonexistent/db.sqlite", "test_ns")
        assert len(result.errors) > 0
