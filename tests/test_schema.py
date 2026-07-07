"""Tests for the SQLite schema module."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.schema import init_schema, table_exists


@pytest.fixture
def conn():
    """In-memory SQLite connection with schema initialised."""
    c = sqlite3.connect(":memory:")
    init_schema(c)
    yield c
    c.close()


class TestIdempotency:
    """INV-11: Schema init must be idempotent."""

    def test_init_twice_no_error(self):
        c = sqlite3.connect(":memory:")
        init_schema(c)
        init_schema(c)  # must not raise
        c.close()


class TestTablesExist:
    """All expected tables must be created."""

    EXPECTED_TABLES = [
        "episodes",
        "facts",
        "narratives",
        "proposal_queue",
        "entities",
        "entity_relations",
        "lessons",
        "fact_conflicts",
        "procedural_rules",
        "rule_conflicts",
        "memory_meta",
        "memory_audit",
    ]

    @pytest.mark.parametrize("table_name", EXPECTED_TABLES)
    def test_table_exists(self, conn, table_name):
        assert table_exists(conn, table_name), f"{table_name} missing"


class TestFTSTables:
    """FTS5 virtual tables must be created."""

    def test_facts_fts_exists(self, conn):
        assert table_exists(conn, "facts_fts")

    def test_episodes_fts_exists(self, conn):
        assert table_exists(conn, "episodes_fts")


class TestFTSTriggers:
    """FTS triggers must sync data on INSERT/DELETE/UPDATE."""

    def test_facts_fts_insert_trigger(self, conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO facts "
            "(id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES ('f_test', 'default', 'Hello world', '[]', "
            "'observation', 1.0, 'evidence', '[]', '2026-01-01', "
            "'2026-01-01')"
        )
        conn.commit()
        cur.execute(
            "SELECT * FROM facts_fts WHERE facts_fts MATCH 'hello'"
        )
        assert cur.fetchone() is not None

    def test_facts_fts_delete_trigger(self, conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO facts "
            "(id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES ('f_del', 'default', 'Delete me', '[]', "
            "'observation', 1.0, 'evidence', '[]', '2026-01-01', "
            "'2026-01-01')"
        )
        conn.commit()
        cur.execute("DELETE FROM facts WHERE id = 'f_del'")
        conn.commit()
        cur.execute(
            "SELECT * FROM facts_fts WHERE facts_fts MATCH 'delete'"
        )
        assert cur.fetchone() is None

    def test_episodes_fts_insert_trigger(self, conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO episodes "
            "(id, namespace, role, origin, content, created_at) "
            "VALUES ('ep_test', 'default', 'user', 'trusted_user', "
            "'Testing FTS episode', '2026-01-01')"
        )
        conn.commit()
        cur.execute(
            "SELECT * FROM episodes_fts WHERE episodes_fts MATCH 'testing'"
        )
        assert cur.fetchone() is not None


class TestIndexes:
    """Key indexes must exist."""

    def test_episode_indexes(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_episodes%'"
        )
        names = {r[0] for r in cur.fetchall()}
        assert "idx_episodes_ns_created" in names
        assert "idx_episodes_unconsumed" in names

    def test_fact_indexes(self, conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_facts%'"
        )
        names = {r[0] for r in cur.fetchall()}
        assert "idx_facts_ns_class_super" in names
        assert "idx_facts_expires" in names


class TestNarrativeUniqueConstraint:
    """Narratives must have UNIQUE(namespace, version)."""

    def test_duplicate_version_raises(self, conn):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO narratives "
            "(id, namespace, version, content, created_at, created_by) "
            "VALUES ('n_1', 'default', 1, 'v1', '2026-01-01', 'human')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute(
                "INSERT INTO narratives "
                "(id, namespace, version, content, created_at, created_by) "
                "VALUES ('n_2', 'default', 1, 'v1dup', '2026-01-01', "
                "'human')"
            )
