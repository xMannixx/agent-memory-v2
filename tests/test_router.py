"""Tests for the StorageRouter."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory_core.config import Config, StorageConfig
from memory_core.router import StorageRouter
from memory_core.schema import table_exists


class TestSingleTopology:
    """Single-DB topology: all namespaces share one file."""

    def test_same_connection_different_namespaces(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="single", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conn_a = router.connect("ns_a")
        conn_b = router.connect("ns_b")
        # In single mode, both resolve to the same DB file.
        assert conn_a is conn_b
        router.close_all()

    def test_schema_initialised(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="single", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conn = router.connect("default")
        assert table_exists(conn, "episodes")
        assert table_exists(conn, "facts")
        assert table_exists(conn, "narratives")
        router.close_all()

    def test_db_file_created(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="single", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        router.connect("default")
        assert (tmp_path / "memory.db").exists()
        router.close_all()


class TestPerNamespaceTopology:
    """Per-namespace topology: one DB file per namespace."""

    def test_different_connections(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conn_a = router.connect("ns_a")
        conn_b = router.connect("ns_b")
        assert conn_a is not conn_b
        router.close_all()

    def test_db_files_created(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        router.connect("alpha")
        router.connect("beta")
        assert (tmp_path / "alpha.db").exists()
        assert (tmp_path / "beta.db").exists()
        router.close_all()

    def test_colon_in_namespace_sanitised(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        router.connect("agent:hermes")
        assert (tmp_path / "agent__hermes.db").exists()
        router.close_all()

    def test_schema_per_file(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conn = router.connect("test_ns")
        assert table_exists(conn, "episodes")
        assert table_exists(conn, "facts")
        router.close_all()


class TestReadMerge:
    """connect_read with include_shared."""

    def test_connect_read_own_only(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conns = router.connect_read("my_ns", include_shared=False)
        assert len(conns) == 1
        router.close_all()

    def test_connect_read_with_shared(self, tmp_path):
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conns = router.connect_read("my_ns", include_shared=True)
        assert len(conns) == 2  # own + shared
        router.close_all()

    def test_connect_read_shared_dedup_single(self, tmp_path):
        """In single mode, shared == own → no duplicate."""
        config = Config(storage=StorageConfig(
            mode="single", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conns = router.connect_read("my_ns", include_shared=True)
        assert len(conns) == 1  # deduplicated
        router.close_all()

    def test_connect_read_shared_namespace_itself(self, tmp_path):
        """Reading 'shared' with include_shared should not duplicate."""
        config = Config(storage=StorageConfig(
            mode="per-namespace", data_dir=str(tmp_path),
        ))
        router = StorageRouter(config)
        conns = router.connect_read("shared", include_shared=True)
        assert len(conns) == 1  # shared == shared
        router.close_all()


class TestOverride:
    """db_path_override for test convenience."""

    def test_memory_override(self):
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        conn = router.connect("anything")
        assert table_exists(conn, "episodes")
        router.close_all()
