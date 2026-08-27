"""Tests for the Audit Log."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory_core.audit import AuditLog
from memory_core.config import Config
from memory_core.router import StorageRouter


@pytest.fixture
def audit():
    config = Config()
    router = StorageRouter(config, db_path_override=":memory:")
    yield AuditLog(router)
    router.close_all()


def test_audit_log_success(audit):
    row_id = audit.log("default", "fact_write", True, reason="human_approved")
    assert row_id > 0
    
    conn = audit._router.connect("default")
    cursor = conn.cursor()
    cursor.execute("SELECT op, accepted, reason FROM memory_audit WHERE id = ?", (row_id,))
    row = cursor.fetchone()
    assert row[0] == "fact_write"
    assert row[1] == 1
    assert row[2] == "human_approved"


def test_audit_invalid_reason_raises(audit):
    with pytest.raises(ValueError, match="Unknown reason code"):
        audit.log("default", "fact_write", False, reason="invalid_reason_xyz")


def test_audit_metadata_json(audit):
    row_id = audit.log("default", "test_op", True, metadata={"key": "val"})
    conn = audit._router.connect("default")
    cursor = conn.cursor()
    cursor.execute("SELECT metadata FROM memory_audit WHERE id = ?", (row_id,))
    meta = cursor.fetchone()[0]
    import json
    assert json.loads(meta) == {"key": "val"}
