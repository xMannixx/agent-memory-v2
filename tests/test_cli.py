"""Tests for the memory_cli."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.cli import main
from src.config import Config
from src.router import StorageRouter


def test_cli_init_command(capsys, monkeypatch, tmp_path):
    # Override config to use tmp_path
    monkeypatch.setenv("MEMORY_CORE_DB_DIR", str(tmp_path))
    
    ret = main(["init", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "Initialized database" in out


def test_cli_db_path_command(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_DB_DIR", str(tmp_path))
    
    ret = main(["db", "path", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "memory.db" in out


def test_cli_queue_ls_empty(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_CORE_DB_DIR", str(tmp_path))
    main(["init", "test_ns"])
    
    ret = main(["queue", "ls", "test_ns"])
    assert ret == 0
    
    out, err = capsys.readouterr()
    assert "No pending proposals." in out


def test_cli_run_missing_api_key(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    ret = main(["run", "test_ns"])
    assert ret == 1
    
    out, err = capsys.readouterr()
    assert "OPENAI_API_KEY environment variable required" in err
