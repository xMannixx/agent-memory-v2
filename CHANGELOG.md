# Changelog

All notable changes to Memory Core v2 will be documented here.

## [2.0.2] — 2026-08-27

### Fixed (Code Review)
- **Gates (G2)**: Gate pipeline no longer mutates the caller's proposal dict. Proposals are deep-copied before evaluation, restoring the "pure functional" guarantee (INV-6).
- **Gates (G2)**: Content length caps now use `content_max_chars` from the lane policy (`AUTHORITY_POLICY`) instead of the unrelated `InjectionConfig` values. Each lane has its own cap.
- **Gates (G2)**: Extended injection pattern detection — now also catches `ignore all`, `disregard`, `override instructions`, `you are now`, `forget your`.
- **Gates (G6)**: Deduplication now also checks `supersede` proposals, preventing duplicate supersede targets.
- **Gates (G7)**: Conflict detection improved for `supersede` proposals on single-valued lanes.
- **Consolidator**: No longer bypasses `FactStore` with raw SQL. Uses `FactStore.write_fact()` and `FactStore.supersede_fact()` for single write path.
- **Queue**: `approve()` now uses `BEGIN IMMEDIATE` to acquire a write lock before reading the proposal, preventing race conditions with concurrent approvers.
- **Queue**: `approve()` now uses the deterministic `narrative_id()` hash instead of `fact_id()` for narrative proposals.
- **Narratives**: `write()` now uses deterministic content-hash IDs (`narrative_id()`) instead of `uuid4()`, satisfying INV-1 (Determinism).
- **Importer**: Entire v3.6 import is now wrapped in a single transaction with rollback on failure, preventing partial imports.
- **OpenAI Adapter**: Robust JSON parsing — handles both `{"proposals": [...]}` and bare `[...]` formats, logs warnings on unexpected shapes, distinguishes `JSONDecodeError` from other failures.
- **Config**: Docstring incorrectly said "TOML config file" for a JSON loader. Corrected.

### Changed
- **Package renamed** from `src` to `memory_core` to avoid namespace collisions with other packages. All internal imports remain relative and are unaffected.
- **Router**: Connection cache is now thread-safe via `threading.Lock`. Connections use `check_same_thread=False` for multi-threaded access.
- **FTS5 Tokenizer**: Changed from `porter` (English-only) to `unicode61` (Unicode-aware, better German support).
- **Fact TTL**: `_touch_facts()` now uses batched per-lane UPDATEs instead of individual per-fact queries, reducing I/O overhead.
- **Lane Policies**: `AUTHORITY_POLICY` now includes `content_max_chars` per lane (identity: 500, preference: 1000, evidence: 2000, authorization: 500, procedural: 1500).
- **Audit**: Added `human_review` to standardized reason codes.
- **Utils**: Shared `utc_now()` / `utc_now_iso()` helpers in `memory_core/utils.py`, eliminating duplicate definitions across 5 modules.
- **`__init__.py`**: Now exports the public API (Config, StorageRouter, Consolidator, FactStore, etc.).
- **Unused imports** cleaned up across `consolidator.py`, `episodes.py`, `audit.py`, `importer.py`.

## [2.0.1] — 2026-08-01

### Fixed
- **CLI**: `queue approve` and `queue reject` crashed with `TypeError: missing 1 required positional argument: 'by'`. Added `--by` flag (defaults to `$USER` or `"cli"`).
- **CLI**: `audit` command crashed with `OperationalError: no such column: operation`. Fixed column names to match actual schema (`op`, `accepted`, `ts`).
- **CLI**: Configuration from environment variables (`MEMORY_CORE_STORAGE_DATA_DIR`, `MEMORY_CORE_STORAGE_MODE`, etc.) was silently ignored. CLI now uses `load_config()` instead of bare `Config()`.
- **Queue**: `approve()` only flipped the queue status without writing the fact to the database. Now performs an atomic commit: writes fact/supersede/narrative + flips status + creates audit entry in a single SQLite transaction with rollback on error.
- **Gates**: Budget counter (G8) incremented for proposals that were subsequently queued, consuming budget without writing facts. Counter now only increments in the consolidator after actual fact commits.
- **Docs**: `CLI.md` referenced non-existent `MEMORY_CORE_DB_DIR` env var. Corrected to `MEMORY_CORE_STORAGE_DATA_DIR`.
- **SKILL.md**: Showed Blocks 2–5 as incomplete despite full implementation. Updated to reflect actual status.

### Changed
- `queue approve` now atomically commits the proposal payload (fact, supersede, or narrative) to the database within the same transaction.
- Budget semantic clarified: `max_new_facts_per_run` counts only actually committed facts, not queued proposals.
- CLI `queue approve`/`reject` commands now accept `--by <operator>` for audit trail identity.

### Tests
- Added 6 new CLI tests covering `queue approve`, `queue reject`, `audit`, and env var propagation.
- Updated `test_queue.py::test_approve` to use realistic payload and verify atomic fact commit.
- Fixed all CLI tests to use correct env var `MEMORY_CORE_STORAGE_DATA_DIR` (was `MEMORY_CORE_DB_DIR`).
- Total: **150 tests passed** (was 144).

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
- **Configuration loader** (`src/config.py`): JSON-based,
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
