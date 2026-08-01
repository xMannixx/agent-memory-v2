# Architecture Overview

Memory Core v2 was designed to solve a specific problem: **LLMs cannot be trusted with direct access to long-term memory.**

When an LLM has direct read/write access to a database (or a JSON file), it is prone to hallucinating facts, breaking schemas, and falling victim to prompt injections stored in past conversations.

Memory Core v2 introduces an impenetrable **Gate Pipeline** between the LLM and the database. The LLM is reduced to an asynchronous *proposer* of facts. The core system deterministically validates, audits, and commits those facts.

## The 5 Core Blocks

The architecture is divided into 5 distinct blocks, all fully implemented:

### Block 1 (B1): The Vault
The foundational storage layer.
- **`src/config.py`**: Three-layer configuration loader (env vars → JSON file → defaults). All settings are exposed via `MEMORY_CORE_*` environment variables.
- **`src/router.py`**: Manages SQLite connections and topology (single-file vs per-namespace).
- **`src/schema.py`**: Idempotent DDL for creating the highly normalized relational schema (Facts, Episodes, Narratives, Audit, Queue, Entities, Lessons, Rules).
- **`src/episodes.py`**: Ingestion layer for raw, unstructured memory (e.g., chat logs, tool outputs).
- **`src/facts.py`**: Read-only Fact API with FTS5 search, German-aware scoring, synonym expansion, and sliding TTL.
- **`src/importer.py`**: Idempotent v3.6 → v2 migration tool.

### Block 2 (B2): The Gates (The Immune System)
A pure-functional pipeline that evaluates LLM proposals.
- **`src/gates.py`**: The 9 deterministic gates:
  - **G1**: Schema & Type Validation
  - **G2**: Anti-Injection (Blocks `SYSTEM:` and triple backticks)
  - **G3**: Evidence Traceability — every fact must reference at least one unconsumed episode
  - **G4**: Origin Ceiling — untrusted origins restrict writes to the `evidence` lane
  - **G5**: Lane Policy — per-lane source/confidence requirements
  - **G6**: Deduplication — content-hash based
  - **G7**: Conflict Detection — single-valued lane collision
  - **G8**: Budget Enforcement — only actually committed facts count toward `max_new_facts_per_run`
  - **G9**: Privileged Queue Routing — routes human-gated lanes to the `proposal_queue`
- **`src/audit.py`**: An append-only log that records *every* gate decision with a fixed reason code.
- **`src/queue.py`**: Proposal lifecycle management. `approve()` atomically commits the proposal payload (fact/supersede/narrative), flips the queue status, and creates an audit entry — all within a single SQLite transaction with rollback on error.

### Block 3 (B3): The Engine
The background worker that digests memory.
- **`src/consolidator.py`**: Fetches unconsumed episodes, builds context, calls the LLM, feeds proposals to the Gate Pipeline, and commits the results. Budget increments happen here (after commit), not in the gate.
- **`src/llm.py`**: Abstract interface for LLM adapters.

### Block 4 (B4): The Context
Bridging the database back to the LLM prompt.
- **`src/narratives.py`**: Manages versioned prose summaries.
- **`src/injection.py`**: Formats the `# Memory Context` block, cleanly truncating facts if the character limit is exceeded.
- **`src/adapters/`**: Houses concrete LLM implementations (e.g., `openai_provider.py`). These are isolated from the core to preserve the stdlib-only invariant.

### Block 5 (B5): The Shell
Packaging and UX.
- **`src/cli.py`**: The `memory-cli` command-line tool (`init`, `db path`, `queue ls|approve|reject`, `audit`, `run`). Uses `load_config()` to respect all environment variables.
- **`pyproject.toml`**: Standard Python packaging configuration.

## Configuration

Settings are loaded via `load_config()` with the following precedence (highest wins):

1. **Environment variables**: `MEMORY_CORE_<SECTION>_<KEY>` (e.g., `MEMORY_CORE_STORAGE_DATA_DIR`)
2. **JSON config file**: Located at `<data_dir>/config.json` or via `MEMORY_CORE_CONFIG`
3. **Hard-coded defaults**: Spec §11

## System Invariants

Memory Core v2 is built upon strict invariants that are continuously tested:

1. **INV-1 (Determinism)**: Given the same DB state and inputs, every core function returns the exact same result.
2. **INV-2 (Stdlib Only)**: The core pipeline imports *only* the Python Standard Library. Zero 3rd-party dependencies.
3. **INV-3 (Async Bounds)**: Memory ingestion (writes) and context retrieval (reads) *never* block on an LLM generation call.
4. **INV-5 (Human-Gated)**: Privileged memory lanes (`identity`, `authorization`, `procedural`) cannot bypass the `proposal_queue`.
5. **INV-6 (Fail-Closed)**: Any exception inside a gate causes an automatic rejection — never a silent pass-through.
6. **INV-7 (Append-Only Audit)**: The audit log can only be inserted into, never updated or deleted.
7. **INV-8 (Evidence-Backed)**: Every fact must reference at least one episode via `evidence_refs`.
8. **INV-10 (Namespace Isolation)**: Writes carry exactly one namespace. The `shared` namespace accepts writes only via the review queue.
9. **INV-11 (Additive Migrations)**: Schema uses `CREATE ... IF NOT EXISTS`. No destructive DDL.
