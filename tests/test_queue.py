"""Tests for the Proposal Queue."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.audit import AuditLog
from src.config import Config
from src.queue import ProposalQueue
from src.router import StorageRouter


@pytest.fixture
def queue():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    audit = AuditLog(router)
    yield ProposalQueue(router, config, audit)
    router.close_all()


def test_enqueue_and_list(queue):
    queue.enqueue("prop_1", "run_1", "default", "fact", {"key": "val"}, {})
    
    pending = queue.list_pending("default")
    assert len(pending) == 1
    assert pending[0].id == "prop_1"
    assert pending[0].payload == {"key": "val"}
    assert pending[0].status == "pending"


def test_approve(queue):
    payload = {
        "content": "Approved fact content",
        "lane": "evidence",
        "confidence": 0.8,
        "source": "inference",
        "evidence_refs": [],
    }
    queue.enqueue("prop_1", "run_1", "default", "fact", payload, {})
    assert queue.approve("default", "prop_1", "human") is True
    
    pending = queue.list_pending("default")
    assert len(pending) == 0
    
    prop = queue.get("default", "prop_1")
    assert prop.status == "approved"
    assert prop.decided_by == "human"
    
    # Verify fact was atomically committed
    conn = queue._router.connect("default")
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM facts WHERE namespace = ?", ("default",))
    rows = cursor.fetchall()
    assert any("Approved fact content" in r[0] for r in rows)


def test_reject(queue):
    queue.enqueue("prop_1", "run_1", "default", "fact", {}, {})
    assert queue.reject("default", "prop_1", "human") is True
    
    prop = queue.get("default", "prop_1")
    assert prop.status == "rejected"


def test_expire_stale(queue, monkeypatch):
    import src.queue
    
    # Enqueue a proposal with current time
    queue.enqueue("prop_1", "run_1", "default", "fact", {}, {})
    
    # Mock time to be far in the future
    future = datetime.now(timezone.utc) + timedelta(days=queue._ttl_days + 2)
    monkeypatch.setattr(src.queue, "_utc_now", lambda: future)
    
    expired_count = queue.expire_stale("default")
    assert expired_count == 1
    
    prop = queue.get("default", "prop_1")
    assert prop.status == "expired"
