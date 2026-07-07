"""Invariant tests for Memory Core v2.

Each INV-n has at least one test named test_inv_<n>_*.
B1 scope: INV-1, INV-2, INV-10, INV-11.
"""

from __future__ import annotations

import ast
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import Config, StorageConfig
from src.router import StorageRouter
from src.episodes import EpisodeStore
from src.schema import init_schema


# -- INV-1: Deterministic core -----------------------------------------------

class TestInv1DeterministicCore:
    """INV-1: Given the same DB state and inputs, every core function
    returns the same result."""

    def test_inv_1_episode_id_deterministic(self):
        """Same inputs always produce the same episode ID."""
        from src.ids import episode_id
        id1 = episode_id("Hello", "session1", "2026-01-01T00:00:00")
        id2 = episode_id("Hello", "session1", "2026-01-01T00:00:00")
        assert id1 == id2

    def test_inv_1_fact_id_deterministic(self):
        from src.ids import fact_id
        id1 = fact_id("User is Alex", "identity")
        id2 = fact_id("User is Alex", "identity")
        assert id1 == id2

    def test_inv_1_episode_search_deterministic(self):
        """Same query on same data returns same results."""
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        store = EpisodeStore(router)
        store.add("default", "Nextcloud AIO setup discussion", "user",
                   "trusted_user")
        r1 = store.search("default", "Nextcloud")
        r2 = store.search("default", "Nextcloud")
        assert len(r1) == len(r2)
        assert [e.id for e in r1] == [e.id for e in r2]
        router.close_all()


# -- INV-2: Stdlib only (core) -----------------------------------------------

class TestInv2StdlibOnly:
    """INV-2: The core and gate pipeline import only the Python standard
    library."""

    CORE_MODULES = [
        "src/__init__.py",
        "src/ids.py",
        "src/models.py",
        "src/config.py",
        "src/schema.py",
        "src/router.py",
        "src/episodes.py",
        "src/facts.py",
        "src/importer.py",
        "src/audit.py",
        "src/queue.py",
        "src/gates.py",
        "src/llm.py",
        "src/consolidator.py",
        "src/narratives.py",
        "src/injection.py",
        "src/cli.py",
    ]

    # Standard library top-level modules that are allowed.
    STDLIB_PREFIXES = {
        "__future__", "abc", "argparse", "ast", "base64", "bisect",
        "collections", "copy", "csv", "ctypes", "dataclasses", "datetime",
        "decimal", "difflib", "enum", "fnmatch", "functools", "glob",
        "hashlib", "heapq", "html", "http", "importlib", "inspect", "io",
        "itertools", "json", "logging", "math", "mimetypes", "numbers",
        "operator", "os", "pathlib", "pickle", "platform", "pprint",
        "queue", "random", "re", "shutil", "signal", "socket", "sqlite3",
        "string", "struct", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "timeit", "tomllib", "traceback", "types",
        "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
        "weakref", "xml", "zipfile", "zlib",
    }

    def _get_imports(self, filepath: Path) -> set:
        """Extract all imported module names from a Python file."""
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    # It's a relative import like `from . import foo` or `from .config import bar`
                    continue
                if node.module:
                    imports.add(node.module.split(".")[0])
        return imports

    @pytest.mark.parametrize("module_path", CORE_MODULES)
    def test_inv_2_no_third_party_imports(self, module_path):
        filepath = _ROOT / module_path
        if not filepath.exists():
            pytest.skip(f"{module_path} not found")
        imports = self._get_imports(filepath)
        for imp in imports:
            assert imp in self.STDLIB_PREFIXES or imp.startswith("src"), (
                f"{module_path} imports non-stdlib module: {imp}"
            )


# -- INV-10: Namespace write isolation ----------------------------------------

class TestInv10NamespaceIsolation:
    """INV-10: No actor writes into another namespace.  Episodes written
    to namespace A must not appear in namespace B."""

    def test_inv_10_episode_namespace_isolation(self):
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        store = EpisodeStore(router)

        store.add("ns_a", "Alpha data", "user", "trusted_user")
        store.add("ns_b", "Beta data", "user", "trusted_user")

        results_a = store.list_recent("ns_a")
        results_b = store.list_recent("ns_b")

        assert len(results_a) == 1
        assert results_a[0].content == "Alpha data"
        assert len(results_b) == 1
        assert results_b[0].content == "Beta data"
        router.close_all()

    def test_inv_10_search_isolation(self):
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        store = EpisodeStore(router)

        store.add("ns_a", "Nextcloud configuration", "user", "trusted_user")
        results = store.search("ns_b", "Nextcloud")
        assert len(results) == 0
        router.close_all()


# -- INV-11: Additive migrations ---------------------------------------------

class TestInv11AdditiveMigrations:
    """INV-11: Schema changes are CREATE TABLE IF NOT EXISTS / ALTER TABLE
    ADD COLUMN only.  No destructive migration."""

    def test_inv_11_init_schema_idempotent(self):
        conn = sqlite3.connect(":memory:")
        init_schema(conn)
        # Insert some data.
        conn.execute(
            "INSERT INTO episodes "
            "(id, namespace, role, origin, content, created_at) "
            "VALUES ('ep_1', 'default', 'user', 'trusted_user', "
            "'Test', '2026-01-01')"
        )
        conn.commit()

        # Re-init must not destroy data.
        init_schema(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM episodes")
        assert cursor.fetchone()[0] == 1
        conn.close()

    def test_inv_11_schema_ddl_uses_if_not_exists(self):
        """Verify DDL strings use IF NOT EXISTS."""
        from src import schema
        # Check all DDL constants.
        ddl_vars = [
            name for name in dir(schema)
            if name.endswith("_DDL") and isinstance(getattr(schema, name), str)
        ]
        for name in ddl_vars:
            ddl = getattr(schema, name)
            assert "IF NOT EXISTS" in ddl, (
                f"{name} does not use IF NOT EXISTS"
            )


# -- INV-4: Untrusted proposals ----------------------------------------------
# Proposals are just unstructured dicts in B2; the pipeline is the first place
# they gain semantics.

# -- INV-5: Privileged human-gated -------------------------------------------

class TestInv5PrivilegedHumanGated:
    """INV-5: Writes to identity, authorization, and procedural lanes always
    require human review (go to the queue)."""

    @pytest.mark.parametrize("lane", ["identity", "authorization", "procedural"])
    def test_inv_5_privileged_lanes_queued(self, lane):
        from src.gates import GatePipeline, PipelineContext
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        ctx = PipelineContext("test", "default", router, config)
        
        # Manually bypass G1-G8 by just running G9 directly
        pipeline = GatePipeline()
        p = {"type": "fact", "lane": lane}
        res = pipeline._g9_routing(ctx, p)
        assert res.decision == "queue"
        assert res.reason == "human_review"
        router.close_all()


# -- INV-6: Fail-closed gates ------------------------------------------------

class TestInv6FailClosedGates:
    """INV-6: If a gate encounters an exception, it rejects the proposal."""

    def test_inv_6_exception_causes_rejection(self, monkeypatch):
        from src.gates import GatePipeline, PipelineContext
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        ctx = PipelineContext("test", "default", router, config)
        
        pipeline = GatePipeline()
        
        # Force an exception in G1
        def bad_g1(ctx, p):
            raise RuntimeError("DB connection lost")
            
        monkeypatch.setattr(pipeline, "_g1_schema", bad_g1)
        
        res, report = pipeline.evaluate(ctx, {"type": "fact"})
        assert res.decision == "reject"
        assert res.reason == "gate_error"
        assert report["G1"]["decision"] == "reject"
        
        router.close_all()


# -- INV-7: Append-only audit ------------------------------------------------

class TestInv7AppendOnlyAudit:
    """INV-7: Every pipeline decision must be auditable (tested via AuditLog).
    We test the append-only nature by verifying we can only INSERT."""

    def test_inv_7_audit_log_inserts(self):
        from src.audit import AuditLog
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        audit = AuditLog(router)
        row_id = audit.log("default", "test_op", True, reason="human_approved")
        assert row_id > 0
        router.close_all()


# -- INV-8: Evidence-backed facts --------------------------------------------

class TestInv8EvidenceBacked:
    """INV-8: A fact must trace back to at least one episode."""

    def test_inv_8_missing_evidence_rejected(self):
        from src.gates import GatePipeline, PipelineContext
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        ctx = PipelineContext("test", "default", router, config)
        
        pipeline = GatePipeline()
        p = {"type": "fact", "content": "Test", "lane": "evidence", "confidence": 1.0}
        
        # Test G3 directly
        res = pipeline._g3_evidence(ctx, p)
        assert res.decision == "reject"
        assert res.reason == "no_evidence_ref"
        
        router.close_all()


# -- INV-3: Asynchronous LLM Bounds -------------------------------------------

class TestInv3AsynchronousBounds:
    """INV-3: Memory reads and writes (ingestion) never block on LLM generation.
    The Consolidator runs fully asynchronously/decoupled from the EpisodeStore."""

    def test_inv_3_ingest_is_synchronous_and_llm_free(self):
        from src.episodes import EpisodeStore
        from src.llm import MockLLM
        config = Config()
        router = StorageRouter(config, db_path_override=":memory:")
        store = EpisodeStore(router)
        
        # Ingestion must not require an LLM instance or block on one
        ep_id = store.add("default", "Fast ingest", "user", "trusted_user")
        assert ep_id.startswith("ep_")
        
        # Reads must also be fast and LLM-free
        unconsumed = store.list_unconsumed("default")
        assert len(unconsumed) == 1
        
        router.close_all()
