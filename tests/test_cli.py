"""Tests for the memory_cli."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.cli import main
from src.audit import AuditLog
from src.config import Config, load_config
from src.queue import ProposalQueue
from src.router import StorageRouter


def test_cli_init_command(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    ret = main(["init", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "Initialized database" in out


def test_cli_db_path_command(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    ret = main(["db", "path", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "memory.db" in out


def test_cli_db_path_respects_env(capsys, monkeypatch, tmp_path):
    """Verify that MEMORY_CORE_STORAGE_DATA_DIR actually changes the resolved path."""
    custom_dir = tmp_path / "custom_data"
    custom_dir.mkdir()
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(custom_dir))
    
    ret = main(["db", "path", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert str(custom_dir) in out.replace("\\", "/").replace(str(custom_dir).replace("\\", "/"), str(custom_dir))
    # More robust: just check the custom dir name is in the output
    assert custom_dir.name in out


def test_cli_queue_ls_empty(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    main(["init", "test_ns"])
    
    ret = main(["queue", "ls", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "No pending proposals." in out


def test_cli_queue_approve(capsys, monkeypatch, tmp_path):
    """End-to-end: enqueue a fact proposal, then approve it via CLI."""
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    # Set up: init namespace and enqueue a proposal directly
    config = load_config()
    router = StorageRouter(config)
    audit = AuditLog(router)
    queue = ProposalQueue(router, config, audit)
    
    router.connect("test_ns")  # init schema
    queue.enqueue(
        "prop_test_1", "run_1", "test_ns", "fact",
        {"content": "Test fact", "lane": "evidence", "confidence": 0.8, "source": "inference", "evidence_refs": []},
        {}
    )
    router.close_all()
    
    # CLI approve
    ret = main(["queue", "approve", "test_ns", "prop_test_1", "--by", "tester"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "Approved prop_test_1" in out


def test_cli_queue_approve_writes_fact(monkeypatch, tmp_path):
    """Verify that approve atomically commits the fact to the facts table."""
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    config = load_config()
    router = StorageRouter(config)
    audit = AuditLog(router)
    queue = ProposalQueue(router, config, audit)
    
    router.connect("test_ns")
    queue.enqueue(
        "prop_fact_commit", "run_1", "test_ns", "fact",
        {"content": "User likes Python", "lane": "preference", "confidence": 0.9, "source": "observation", "evidence_refs": []},
        {}
    )
    
    # Approve
    assert queue.approve("test_ns", "prop_fact_commit", "tester") is True
    
    # Verify fact was written
    conn = router.connect("test_ns")
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM facts WHERE namespace = ?", ("test_ns",))
    rows = cursor.fetchall()
    assert any("User likes Python" in r[0] for r in rows)
    
    router.close_all()


def test_cli_queue_reject(capsys, monkeypatch, tmp_path):
    """End-to-end: enqueue then reject via CLI."""
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    config = load_config()
    router = StorageRouter(config)
    audit = AuditLog(router)
    queue = ProposalQueue(router, config, audit)
    
    router.connect("test_ns")
    queue.enqueue(
        "prop_test_2", "run_1", "test_ns", "fact",
        {"content": "Rejected fact", "lane": "evidence", "confidence": 0.5, "source": "inference", "evidence_refs": []},
        {}
    )
    router.close_all()
    
    ret = main(["queue", "reject", "test_ns", "prop_test_2", "--by", "admin"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "Rejected prop_test_2" in out


def test_cli_audit_command(capsys, monkeypatch, tmp_path):
    """Verify the audit command runs without column errors."""
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    main(["init", "test_ns"])
    
    # The init itself doesn't write audit entries, but the command should not crash
    ret = main(["audit", "test_ns", "-n", "5"])
    assert ret == 0


def test_cli_audit_shows_entries(capsys, monkeypatch, tmp_path):
    """Verify audit output contains entries after queue operations."""
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    
    config = load_config()
    router = StorageRouter(config)
    audit = AuditLog(router)
    queue = ProposalQueue(router, config, audit)
    
    router.connect("test_ns")
    queue.enqueue(
        "prop_aud", "run_1", "test_ns", "fact",
        {"content": "Audit test", "lane": "evidence", "confidence": 0.7, "source": "inference", "evidence_refs": []},
        {}
    )
    router.close_all()
    
    ret = main(["audit", "test_ns", "-n", "5"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "proposal_queued" in out
    assert "SUCCESS" in out


def test_cli_run_missing_api_key(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    ret = main(["run", "test_ns"])
    assert ret == 1
    
    out, err = capsys.readouterr()
    assert "OPENAI_API_KEY environment variable required" in err


def test_cli_queue_approve_missing_returns_error(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    main(["init", "test_ns"])
    
    ret = main(["queue", "approve", "test_ns", "missing"])
    assert ret == 1
    
    out, err = capsys.readouterr()
    assert "Proposal not found or not pending: missing" in err


def test_cli_queue_reject_missing_returns_error(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_STORAGE_DATA_DIR", str(tmp_path))
    main(["init", "test_ns"])
    
    ret = main(["queue", "reject", "test_ns", "missing"])
    assert ret == 1
    
    out, err = capsys.readouterr()
    assert "Proposal not found or not pending: missing" in err
