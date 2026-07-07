"""Tests for the TOML configuration loader."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Ensure src is importable.
import sys
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import load_config, Config


class TestDefaults:
    """Verify that defaults match spec §11."""

    def test_default_storage_mode(self):
        config = load_config()
        assert config.storage.mode == "single"

    def test_default_data_dir(self):
        config = load_config()
        assert config.storage.data_dir == "~/.memory-core"

    def test_default_consolidator_backend(self):
        config = load_config()
        assert config.consolidator.backend == "command"

    def test_default_narrative_max_chars(self):
        config = load_config()
        assert config.narrative.max_chars == 2000

    def test_default_injection_identity(self):
        config = load_config()
        assert config.injection.identity == 500

    def test_resolved_data_dir_expands_tilde(self):
        config = load_config()
        resolved = config.resolved_data_dir
        assert "~" not in str(resolved)
        assert resolved.is_absolute()


class TestJsonFile:
    """Verify JSON file loading."""

    def test_json_overrides_defaults(self, tmp_path):
        json_file = tmp_path / "config.json"
        json_file.write_text(
            '{"storage": {"mode": "per-namespace", "data_dir": "/tmp/test"}, "narrative": {"max_chars": 1500}}'
        )
        config = load_config(str(json_file))
        assert config.storage.mode == "per-namespace"
        assert config.storage.data_dir == "/tmp/test"
        assert config.narrative.max_chars == 1500
        # Unchanged sections keep defaults.
        assert config.consolidator.max_episodes_per_run == 200

    def test_missing_json_uses_defaults(self):
        config = load_config("/nonexistent/path/config.json")
        assert config.storage.mode == "single"


class TestEnvOverrides:
    """Verify environment variable overrides."""

    def test_env_overrides_string(self, monkeypatch):
        monkeypatch.setenv("MEMORY_CORE_STORAGE_MODE", "per-namespace")
        config = load_config()
        assert config.storage.mode == "per-namespace"

    def test_env_overrides_int(self, monkeypatch):
        monkeypatch.setenv("MEMORY_CORE_NARRATIVE_MAX_CHARS", "3000")
        config = load_config()
        assert config.narrative.max_chars == 3000

    def test_env_overrides_bool_true(self, monkeypatch):
        monkeypatch.setenv("MEMORY_CORE_NARRATIVE_REVIEW", "true")
        config = load_config()
        assert config.narrative.review is True

    def test_env_overrides_bool_false(self, monkeypatch):
        monkeypatch.setenv("MEMORY_CORE_NAMESPACES_DEFAULT_READ_SHARED", "0")
        config = load_config()
        assert config.namespaces.default_read_shared is False

    def test_invalid_int_keeps_default(self, monkeypatch):
        monkeypatch.setenv("MEMORY_CORE_NARRATIVE_MAX_CHARS", "not_a_number")
        config = load_config()
        assert config.narrative.max_chars == 2000

    def test_env_beats_json(self, tmp_path, monkeypatch):
        json_file = tmp_path / "config.json"
        json_file.write_text('{"narrative": {"max_chars": 1500}}')
        monkeypatch.setenv("MEMORY_CORE_NARRATIVE_MAX_CHARS", "999")
        config = load_config(str(json_file))
        assert config.narrative.max_chars == 999
