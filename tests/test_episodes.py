"""Tests for the Episode API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory_core.config import Config
from memory_core.router import StorageRouter
from memory_core.episodes import EpisodeStore, VALID_ORIGINS, VALID_ROLES


@pytest.fixture
def store():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    yield EpisodeStore(router)
    router.close_all()


class TestAdd:
    """Episode ingestion."""

    def test_add_returns_id(self, store):
        ep_id = store.add("default", "Hello world", "user", "trusted_user")
        assert ep_id.startswith("ep_")

    def test_add_idempotent(self, store, monkeypatch):
        import datetime
        from datetime import timezone
        fixed_time = datetime.datetime(2026, 1, 1, tzinfo=timezone.utc)
        
        # We need to mock _utc_now in src.episodes
        import memory_core.episodes
        monkeypatch.setattr(memory_core.episodes, "_utc_now", lambda: fixed_time)
        
        id1 = store.add("default", "Same content", "user", "trusted_user")
        id2 = store.add("default", "Same content", "user", "trusted_user")
        assert id1 == id2

    def test_add_invalid_role_raises(self, store):
        with pytest.raises(ValueError, match="Invalid role"):
            store.add("default", "Bad role", "invalid_role", "trusted_user")

    def test_add_invalid_origin_raises(self, store):
        with pytest.raises(ValueError, match="Invalid origin"):
            store.add("default", "Bad origin", "user", "not_a_real_origin")

    def test_add_empty_content_raises(self, store):
        with pytest.raises(ValueError, match="must not be empty"):
            store.add("default", "", "user", "trusted_user")

    def test_add_whitespace_content_raises(self, store):
        with pytest.raises(ValueError, match="must not be empty"):
            store.add("default", "   ", "user", "trusted_user")

    def test_add_with_session_id(self, store):
        ep_id = store.add(
            "default", "With session", "user", "trusted_user",
            session_id="ses_123",
        )
        ep = store.get("default", ep_id)
        assert ep is not None
        assert ep.session_id == "ses_123"

    def test_add_with_metadata(self, store):
        ep_id = store.add(
            "default", "With meta", "tool", "tool_output",
            metadata={"tool_name": "web_search"},
        )
        ep = store.get("default", ep_id)
        assert ep.metadata["tool_name"] == "web_search"

    def test_all_valid_origins(self, store):
        for origin in VALID_ORIGINS:
            ep_id = store.add("default", f"Test {origin}", "user", origin)
            assert ep_id.startswith("ep_")

    def test_all_valid_roles(self, store):
        for role in VALID_ROLES:
            ep_id = store.add("default", f"Test {role}", role, "trusted_user")
            assert ep_id.startswith("ep_")


class TestSearch:
    """FTS5 search."""

    def test_search_finds_match(self, store):
        store.add("default", "Nextcloud AIO configuration", "user",
                   "trusted_user")
        results = store.search("default", "Nextcloud")
        assert len(results) >= 1
        assert "Nextcloud" in results[0].content

    def test_search_no_match(self, store):
        store.add("default", "Something else entirely", "user",
                   "trusted_user")
        results = store.search("default", "Kubernetes")
        assert len(results) == 0

    def test_search_namespace_isolation(self, store):
        store.add("ns_a", "Alpha data", "user", "trusted_user")
        results = store.search("ns_b", "Alpha")
        assert len(results) == 0

    def test_search_respects_limit(self, store):
        for i in range(10):
            store.add("default", f"Document number {i} about testing",
                       "user", "trusted_user")
        results = store.search("default", "Document", limit=3)
        assert len(results) <= 3


class TestListAndGet:
    """Listing and fetching episodes."""

    def test_list_unconsumed(self, store):
        store.add("default", "Unconsumed episode", "user", "trusted_user")
        results = store.list_unconsumed("default")
        assert len(results) >= 1
        assert all(e.consumed_by is None for e in results)

    def test_list_recent(self, store):
        store.add("default", "Recent episode", "user", "trusted_user")
        results = store.list_recent("default")
        assert len(results) >= 1

    def test_get_existing(self, store):
        ep_id = store.add("default", "Get me", "user", "trusted_user")
        ep = store.get("default", ep_id)
        assert ep is not None
        assert ep.id == ep_id
        assert ep.content == "Get me"

    def test_get_nonexistent(self, store):
        ep = store.get("default", "ep_doesnotexist")
        assert ep is None


class TestMarkConsumed:
    """Consumption marking for consolidator."""

    def test_mark_consumed(self, store):
        ep_id = store.add("default", "To consume", "user", "trusted_user")
        count = store.mark_consumed("default", [ep_id], "run_001")
        assert count == 1
        # Should no longer appear in unconsumed list.
        unconsumed = store.list_unconsumed("default")
        assert all(e.id != ep_id for e in unconsumed)

    def test_mark_consumed_idempotent(self, store):
        ep_id = store.add("default", "To consume twice", "user",
                           "trusted_user")
        store.mark_consumed("default", [ep_id], "run_001")
        count = store.mark_consumed("default", [ep_id], "run_002")
        assert count == 0  # already consumed

    def test_mark_consumed_empty_list(self, store):
        count = store.mark_consumed("default", [], "run_001")
        assert count == 0


class TestStats:
    """Episode statistics."""

    def test_stats_empty(self, store):
        stats = store.stats("default")
        assert stats["total"] == 0
        assert stats["unconsumed"] == 0

    def test_stats_after_adds(self, store):
        store.add("default", "Ep 1", "user", "trusted_user")
        store.add("default", "Ep 2", "assistant", "trusted_user")
        stats = store.stats("default")
        assert stats["total"] == 2
        assert stats["unconsumed"] == 2
        assert stats["by_role"]["user"] == 1
        assert stats["by_role"]["assistant"] == 1
