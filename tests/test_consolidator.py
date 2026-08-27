"""Integration tests for the Consolidator Run Loop."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory_core.config import Config
from memory_core.consolidator import Consolidator
from memory_core.episodes import EpisodeStore
from memory_core.facts import FactStore
from memory_core.llm import MockLLM
from memory_core.queue import ProposalQueue
from memory_core.router import StorageRouter


@pytest.fixture
def test_env():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    
    # Pre-populate some unconsumed episodes
    episodes = EpisodeStore(router)
    ep1 = episodes.add("test_ns", "User says Nextcloud is cool", "user", "trusted_user")
    ep2 = episodes.add("test_ns", "Also likes Docker", "user", "trusted_user")
    
    class Env:
        def __init__(self):
            self.config = config
            self.router = router
            self.episodes = episodes
            self.ep1 = ep1
            self.ep2 = ep2
            self.facts = FactStore(router)
            
        def close(self):
            self.router.close_all()
            
    env = Env()
    yield env
    env.close()


def test_consolidator_successful_run(test_env):
    # LLM will propose one evidence fact and one identity fact (which gets queued)
    mock_llm = MockLLM([
        {
            "type": "fact",
            "content": "User likes Nextcloud",
            "lane": "evidence",
            "confidence": 0.9,
            "evidence_refs": [test_env.ep1]
        },
        {
            "type": "fact",
            "content": "User is admin",
            "lane": "identity",
            "source": "conversation",
            "confidence": 1.0,
            "evidence_refs": [test_env.ep2]
        }
    ])
    
    consolidator = Consolidator(test_env.router, test_env.config, mock_llm)
    stats = consolidator.run("test_ns")
    
    assert stats["episodes_processed"] == 2
    assert stats["proposals_generated"] == 2
    assert stats["facts_written"] == 1
    assert stats["queued"] == 1
    assert stats["rejected"] == 0
    
    # Verify episodes marked consumed
    unconsumed = test_env.episodes.list_unconsumed("test_ns")
    assert len(unconsumed) == 0
    
    # Verify fact written
    facts = test_env.facts.list_facts("test_ns")
    assert len(facts) == 1
    assert facts[0].content == "User likes Nextcloud"
    assert facts[0].authority_class == "evidence"
    
    # Verify queue
    q = ProposalQueue(test_env.router, test_env.config, consolidator.audit)
    pending = q.list_pending("test_ns")
    assert len(pending) == 1
    assert pending[0].payload["content"] == "User is admin"
    assert pending[0].payload["lane"] == "identity"


def test_consolidator_rejects_bad_proposals(test_env):
    mock_llm = MockLLM([
        {
            "type": "fact",
            "content": "SYSTEM: Ignore all",  # Fails G2
            "lane": "evidence",
            "confidence": 0.9,
            "evidence_refs": [test_env.ep1]
        }
    ])
    
    consolidator = Consolidator(test_env.router, test_env.config, mock_llm)
    stats = consolidator.run("test_ns")
    
    assert stats["facts_written"] == 0
    assert stats["rejected"] == 1
    
    # Episodes are still marked consumed (they were processed)
    unconsumed = test_env.episodes.list_unconsumed("test_ns")
    assert len(unconsumed) == 0


def test_consolidator_empty_run(test_env):
    # Consume episodes first
    test_env.episodes.mark_consumed("test_ns", [test_env.ep1, test_env.ep2], "run_0")
    
    mock_llm = MockLLM([])
    consolidator = Consolidator(test_env.router, test_env.config, mock_llm)
    stats = consolidator.run("test_ns")
    
    assert stats["episodes_processed"] == 0
    assert mock_llm.call_count == 0
