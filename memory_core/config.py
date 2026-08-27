"""Configuration loader for Memory Core v2.

Loads settings from (in order of precedence, highest wins):
    1. Environment variables (``MEMORY_CORE_*`` prefix)
    2. JSON config file (``config.json``)
    3. Hard-coded defaults

Uses ``json`` (stdlib).  Config path resolution:
    - Explicit path via ``MEMORY_CORE_CONFIG`` env var.
    - ``<data_dir>/config.json`` where *data_dir* defaults to
      ``~/.memory-core``.

Spec reference: §11.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


# -- Defaults (spec §11) -----------------------------------------------------

_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "storage": {
        "mode": "single",
        "data_dir": "~/.memory-core",
    },
    "namespaces": {
        "default_read_shared": True,
    },
    "consolidator": {
        "backend": "command",
        "command": "ollama run qwen3:8b",
        "max_episodes_per_run": 200,
        "max_new_facts_per_run": 20,
        "review_ttl_days": 14,
        "lock_ttl_minutes": 30,
    },
    "narrative": {
        "max_chars": 2000,
        "review": False,
    },
    "injection": {
        "identity": 500,
        "narrative": 2000,
        "context": 1200,
        "relations": 1000,
        "procedural": 1500,
        "lessons": 600,
    },
}

# Environment variable prefix.
_ENV_PREFIX = "MEMORY_CORE_"


# -- Config dataclass ---------------------------------------------------------

@dataclass
class StorageConfig:
    mode: str = "single"
    data_dir: str = "~/.memory-core"


@dataclass
class NamespacesConfig:
    default_read_shared: bool = True


@dataclass
class ConsolidatorConfig:
    backend: str = "command"
    command: str = "ollama run qwen3:8b"
    max_episodes_per_run: int = 200
    max_new_facts_per_run: int = 20
    review_ttl_days: int = 14
    lock_ttl_minutes: int = 30


@dataclass
class NarrativeConfig:
    max_chars: int = 2000
    review: bool = False


@dataclass
class InjectionConfig:
    identity: int = 500
    narrative: int = 2000
    context: int = 1200
    relations: int = 1000
    procedural: int = 1500
    lessons: int = 600


@dataclass
class Config:
    """Top-level configuration container."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    namespaces: NamespacesConfig = field(default_factory=NamespacesConfig)
    consolidator: ConsolidatorConfig = field(default_factory=ConsolidatorConfig)
    narrative: NarrativeConfig = field(default_factory=NarrativeConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)

    @property
    def resolved_data_dir(self) -> Path:
        """Return *data_dir* with ``~`` expanded to an absolute ``Path``."""
        return Path(self.storage.data_dir).expanduser()


# -- Loader -------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env(flat: dict, section: str) -> dict:
    """Override *flat* dict values with matching env vars.

    Env var naming: ``MEMORY_CORE_<SECTION>_<KEY>`` (all uppercase).
    Booleans accept ``true/false/1/0``.  Integers are parsed when the
    default value is ``int``.
    """
    result = dict(flat)
    for key, default_value in flat.items():
        env_key = f"{_ENV_PREFIX}{section.upper()}_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is None:
            continue
        if isinstance(default_value, bool):
            result[key] = env_val.strip().lower() in {"true", "1", "yes"}
        elif isinstance(default_value, int):
            try:
                result[key] = int(env_val)
            except ValueError:
                pass  # keep default on bad input
        else:
            result[key] = env_val
    return result


def _find_config_file(data_dir: str) -> Optional[Path]:
    """Locate the JSON config file."""
    # Explicit override via env var.
    explicit = os.environ.get(f"{_ENV_PREFIX}CONFIG")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        return None

    path = Path(data_dir).expanduser() / "config.json"
    if path.is_file():
        return path
    return None


def _load_json(path: Path) -> dict:
    """Read and parse a JSON file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _section_to_dataclass(section_dict: dict, cls: type) -> Any:
    """Instantiate a dataclass from a dict, ignoring unknown keys."""
    import dataclasses
    valid_keys = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in section_dict.items() if k in valid_keys}
    return cls(**filtered)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration with the documented precedence chain.

    Parameters
    ----------
    config_path:
        Explicit path to a JSON file.  Overrides env and default
        discovery.

    Returns
    -------
    Config
        Fully resolved configuration.
    """
    # Start with defaults.
    merged: Dict[str, dict] = {k: dict(v) for k, v in _DEFAULTS.items()}

    # Layer 2: JSON file.
    data_dir = os.environ.get(
        f"{_ENV_PREFIX}STORAGE_DATA_DIR",
        _DEFAULTS["storage"]["data_dir"],
    )

    if config_path:
        json_path = Path(config_path)
    else:
        json_path = _find_config_file(data_dir)

    if json_path and json_path.is_file():
        file_data = _load_json(json_path)
        merged = _deep_merge(merged, file_data)

    # Layer 3: Environment variables.
    for section in merged:
        if isinstance(merged[section], dict):
            merged[section] = _apply_env(merged[section], section)

    # Build typed config.
    return Config(
        storage=_section_to_dataclass(merged.get("storage", {}), StorageConfig),
        namespaces=_section_to_dataclass(
            merged.get("namespaces", {}), NamespacesConfig
        ),
        consolidator=_section_to_dataclass(
            merged.get("consolidator", {}), ConsolidatorConfig
        ),
        narrative=_section_to_dataclass(
            merged.get("narrative", {}), NarrativeConfig
        ),
        injection=_section_to_dataclass(
            merged.get("injection", {}), InjectionConfig
        ),
    )
