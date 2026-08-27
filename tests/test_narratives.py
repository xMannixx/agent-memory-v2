"""Tests for the Narrative Layer and Injection Formatting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory_core.config import Config
from memory_core.facts import FactStore
from memory_core.injection import get_injection_block
from memory_core.narratives import NarrativeStore
from memory_core.router import StorageRouter


@pytest.fixture
def store_env():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    
    class Env:
        def __init__(self):
            self.config = config
            self.router = router
            self.narratives = NarrativeStore(router, config)
            self.facts = FactStore(router)
            
        def close(self):
            self.router.close_all()
            
    env = Env()
    yield env
    env.close()


def test_narrative_write_and_read(store_env):
    ns = "test_ns"
    n1_id = store_env.narratives.write(ns, "First version", "test")
    n1 = store_env.narratives.get_latest(ns)
    assert n1.id == n1_id
    assert n1.version == 1
    assert n1.content == "First version"
    
    n2_id = store_env.narratives.write(ns, "Second version", "test")
    n2 = store_env.narratives.get_latest(ns)
    assert n2.id == n2_id
    assert n2.version == 2
    assert n2.content == "Second version"


def test_injection_block_formatting(store_env):
    ns = "test_ns"
    store_env.narratives.write(ns, "The user is a developer.", "test")
    
    # Write a fact (bypassing normal pipelines for speed)
    conn = store_env.router.connect(ns)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO facts (id, namespace, content, authority_class, source, confidence, created_at, last_accessed) "
        "VALUES ('f1', ?, 'Likes Python', 'evidence', 'observation', 1.0, '2026-01-01', '2026-01-01')",
        (ns,)
    )
    conn.commit()
    
    block = get_injection_block(ns, store_env.narratives, store_env.facts, store_env.config)
    assert "# Memory Context" in block
    assert "The user is a developer." in block
    assert "Relevant Facts:" in block
    assert "- Likes Python" in block


def test_injection_block_truncation(store_env):
    ns = "test_ns"
    store_env.narratives.write(ns, "A" * 5000, "test")  # Huge narrative
    
    # Artificially lower the limit
    store_env.config.narrative.max_chars = 100
    
    block = get_injection_block(ns, store_env.narratives, store_env.facts, store_env.config)
    
    # Should be capped at 100 chars
    assert len(block) == 100
    assert block.endswith("...")
    assert "Relevant Facts:" not in block  # Facts dropped due to limit
