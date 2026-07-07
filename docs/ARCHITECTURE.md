# Architecture Overview

Memory Core v2 was designed to solve a specific problem: **LLMs cannot be trusted with direct access to long-term memory.**

When an LLM has direct read/write access to a database (or a JSON file), it is prone to hallucinating facts, breaking schemas, and falling victim to prompt injections stored in past conversations.

Memory Core v2 introduces an impenetrable **Gate Pipeline** between the LLM and the database. The LLM is reduced to an asynchronous *proposer* of facts. The core system deterministically validates, audits, and commits those facts.

## The 5 Core Blocks

The architecture is divided into 5 distinct blocks, implemented sequentially:

### Block 1 (B1): The Vault
The foundational storage layer.
- **`src/router.py`**: Manages SQLite connections and topology (single-file vs per-namespace).
- **`src/schema.py`**: Idempotent DDL for creating the highly normalized relational schema (Facts, Episodes, Narratives, Audit, Queue).
- **`src/episodes.py`**: Ingestion layer for raw, unstructured memory (e.g., chat logs, tool outputs).

### Block 2 (B2): The Gates (The Immune System)
A pure-functional pipeline that evaluates LLM proposals.
- **`src/gates.py`**: The 9 deterministic gates:
  - **G1**: Schema & Type Validation
  - **G2**: Anti-Injection (Blocks `SYSTEM:` and triple backticks)
  - **G3 & G8**: Evidence Traceability & Budgeting
  - **G4 & G5**: Lane Policy Enforcement (e.g. inference cannot write to `identity`)
  - **G6 & G7**: Deduplication and Single-Value Conflict resolution
  - **G9**: Privileged Queue Routing (Routes human-gated lanes to the `proposal_queue`)
- **`src/audit.py`**: An append-only log that records *every* gate decision with a fixed reason code.
- **`src/queue.py`**: API for managing pending proposals requiring human approval.

### Block 3 (B3): The Engine
The background worker that digests memory.
- **`src/consolidator.py`**: Fetches unconsumed episodes, builds context, calls the LLM, feeds proposals to the Gate Pipeline, and commits the results.
- **`src/llm.py`**: Abstract interface for LLM adapters.

### Block 4 (B4): The Context
Bridging the database back to the LLM prompt.
- **`src/narratives.py`**: Manages versioned prose summaries.
- **`src/injection.py`**: Formats the `# Memory Context` block, cleanly truncating facts if the character limit is exceeded.
- **`src/adapters/`**: Houses concrete LLM implementations (e.g., `openai_provider.py`). These are isolated from the core to preserve the stdlib-only invariant.

### Block 5 (B5): The Shell
Packaging and UX.
- **`src/cli.py`**: The `memory-cli` command-line tool.
- **`pyproject.toml`**: Standard Python packaging configuration.

## System Invariants

Memory Core v2 is built upon strict invariants that are continuously tested:

1. **INV-1 (Determinism)**: Given the same DB state and inputs, every core function returns the exact same result.
2. **INV-2 (Stdlib Only)**: The core pipeline imports *only* the Python Standard Library. Zero 3rd-party dependencies.
3. **INV-3 (Async Bounds)**: Memory ingestion (writes) and context retrieval (reads) *never* block on an LLM generation call.
4. **INV-5 (Human-Gated)**: Privileged memory lanes (`identity`, `authorization`, `procedural`) cannot bypass the `proposal_queue`.
5. **INV-7 (Append-Only Audit)**: The audit log can only be inserted into, never updated or deleted.
