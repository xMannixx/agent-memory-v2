"""Corpus-driven tests for the Gate Pipeline (G1-G9).

Runs the deterministic JSON test suite against the gate logic.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import Config
from src.gates import GatePipeline, PipelineContext
from src.router import StorageRouter


def load_corpus() -> list:
    corpus_file = Path(__file__).parent / "fixtures" / "gate_corpus.json"
    with corpus_file.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def empty_router():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    yield router
    router.close_all()


@pytest.mark.parametrize("case", load_corpus(), ids=lambda c: c["id"])
def test_gate_corpus(case, empty_router):
    router = empty_router
    config = Config()
    
    # 1. Setup DB state
    conn = router.connect("default")
    cursor = conn.cursor()
    
    setup = case.get("db_setup", {})
    
    # Episodes
    for ep in setup.get("episodes", []):
        cursor.execute(
            "INSERT INTO episodes (id, namespace, role, origin, content, created_at) "
            "VALUES (?, 'default', 'user', ?, 'dummy content', '2026-01-01')",
            (ep["id"], ep["origin"])
        )
        
    # Facts
    for f in setup.get("facts", []):
        cursor.execute(
            "INSERT INTO facts (id, namespace, content, authority_class, source, confidence, created_at, last_accessed, superseded_by) "
            "VALUES (?, 'default', ?, ?, 'observation', 1.0, '2026-01-01', '2026-01-01', ?)",
            (f["id"], f["content"], f["lane"], f.get("superseded_by"))
        )
        
    conn.commit()
    
    # 2. Evaluate
    pipeline = GatePipeline()
    ctx = PipelineContext("run_test", "default", router, config)
    
    proposal = dict(case["proposal"])  # copy so we don't mutate the fixture
    result, report = pipeline.evaluate(ctx, proposal)
    
    # 3. Assert
    assert result.decision == case["expected_decision"], f"Failed case {case['id']}: expected {case['expected_decision']}, got {result.decision} ({result.reason})"
    
    if case["expected_reason"]:
        assert result.reason == case["expected_reason"], f"Failed case {case['id']}: expected reason {case['expected_reason']}, got {result.reason}"
