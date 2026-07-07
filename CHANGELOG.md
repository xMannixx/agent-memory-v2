# Changelog

All notable changes to Memory Core v2 will be documented here.

## [2.0.0] — 2026-07-07

### Added (Block 5)
- **Packaging**: Created `pyproject.toml` to define `memory-core` as a standard pip-installable package. Optional `[openai]` extra added.
- **CLI** (`src/cli.py`): Implemented the `memory-cli` command-line tool.
  - `init`: Create/update schema for a namespace.
  - `db path`: Return the absolute path to the SQLite file.
  - `queue ls | approve | reject`: View and manage the proposal queue for human-gated memory lanes.
  - `audit`: Tail the immutable append-only audit log.
  - `run`: Trigger a manual consolidator pass.
- **Tests**: `test_cli.py` covers basic arg parsing and routing. Added `cli.py` to the INV-2 stdlib test to guarantee no external dependencies sneaked into the core logic.

## [2.0.0-dev] — Block 4 (B4)

### Added
- **Narrative Layer** (`src/narratives.py`): Immutable, versioned narrative storage.
- **Injection Formatter** (`src/injection.py`): Assembles the `# Memory Context` block (narrative + dynamic facts) and enforces config-based token/character limits via graceful truncation.
- **OpenAI Adapter** (`src/adapters/openai_provider.py`): The first concrete `LLMProvider` using the official OpenAI client and strict `json_object` formatting. Placed in `adapters/` to maintain the stdlib-only guarantee for the core pipeline.
- **Tests**: `test_narratives.py` and `test_openai_adapter.py`. Core invariant tests (INV-2) updated to verify all new core modules while properly isolating adapters.

## [2.0.0-dev] — Block 3 (B3)

### Added
- **LLM Interface** (`src/llm.py`): Abstract `LLMProvider` and a `MockLLM` for deterministic testing without external API calls.
- **Consolidator Run Loop** (`src/consolidator.py`): The core background worker that:
  1. Fetches unconsumed episodes.
  2. Retrieves context facts via `facts.recall`.
  3. Prompts the LLM for JSON proposals.
  4. Runs proposals through the Gate Pipeline (B2).
  5. Commits valid proposals to the DB and marks episodes consumed.
- **Integration Tests**: `tests/test_consolidator.py` verifies the entire ingestion -> digest -> gate -> commit pipeline.
- **Invariant Tests**: Added INV-3 (Asynchronous LLM Bounds).

## [2.0.0-dev] — Block 2 (B2)

### Added
- **Audit Log** (`src/audit.py`): Append-only `memory_audit` wrapper (INV-7) enforcing strict reason codes.
- **Proposal Queue** (`src/queue.py`): Pending write lifecycle, enforced TTL, and human-approval handling.
- **Gate Pipeline** (`src/gates.py`): Deterministic G1-G9 evaluation. 
  - G1: Strict schema/type validation.
  - G2: Anti-injection sanitization (`SYSTEM:`, code fences) and length caps.
  - G3/G8: Evidence traceability (INV-8) and budget enforcement.
  - G4/G5/G9: Lane policy and privileged origin ceilings (INV-5).
- **Test Corpus** (`tests/fixtures/gate_corpus.json`): Exhaustive JSON deterministic test vectors covering all gate policies.
- **Invariant Tests**: Expanded `test_invariants.py` for INV-4 (Untrusted), INV-5 (Human-gated), INV-6 (Fail-closed), INV-7, and INV-8.

## [2.0.0-dev] — Block 1 (B1)

### Added
- **Repo skeleton** with `src/` package, `cli/`, `tests/`.
- **Configuration loader** (`src/config.py`): TOML-based (`tomllib`),
  env var overrides (`MEMORY_CORE_*`), three-layer precedence chain.
- **Schema** (`src/schema.py`): All v2 tables (episodes, facts,
  narratives, proposal_queue, entities, entity_relations, lessons,
  fact_conflicts, procedural_rules, rule_conflicts, memory_meta,
  memory_audit) with FTS5 virtual tables and triggers.  Fully
  idempotent (INV-11).
- **StorageRouter** (`src/router.py`): Two topologies (`single`,
  `per-namespace`), connection caching, auto schema init.
- **Episode API** (`src/episodes.py`): Append-only ingestion with
  origin/role validation, FTS5 search, unconsumed listing,
  consumption marking, staleness cleanup, anomaly detection.
- **Fact Store** (`src/facts.py`): Read-only API with FTS5 search,
  German-aware scoring, synonym expansion, sliding TTL, namespace
  merge reads.
- **v3.6 Importer** (`src/importer.py`): Migrates facts, snippets →
  episodes, lessons, entities, relations, procedural rules, conflicts,
  meta, and audit.  Idempotent, dry-runnable.
- **Data models** (`src/models.py`): Frozen dataclasses for Episode,
  Fact, Narrative, Proposal, Lesson, Entity.
- **ID generation** (`src/ids.py`): Content-hash IDs with type prefixes.
- **German-aware retrieval** (`src/text_norm.py`, `src/synonyms.json`):
  Ported 1:1 from v3.6.
- **CLI** (`cli/memoryctl.py`): Unified entry point with subcommands
  `episode add|search|list|stats`, `fact recall|list|get`,
  `stats`, `import --from-v3`.
- **Tests**: config, schema, router, episodes, importer, invariants
  (INV-1, INV-2, INV-10, INV-11).

### Changed from v3.6
- `recall_snippets` replaced by episodes (append-only, origin-tracked).
- Rebound-Protection removed (obsolete under INV-3; replaced by
  per-run consolidation budgets in B2).
- All tables gain a `namespace` column.
- Facts gain an `evidence_refs` column (JSON list of episode IDs).
- `memory_meta` primary key is now `(key, namespace)`.
