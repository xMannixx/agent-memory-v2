# Memory Core v2

An append-only, deterministic, stdlib-only core library for managing long-term agent memory.

Memory Core v2 provides a framework-agnostic pipeline that accepts raw "episodes" (e.g. chat messages, tool outputs), passes them through a deterministic Gate Pipeline (for schema validation, injection prevention, source filtering), and outputs structured "facts" and "narratives".

## Features
- **Deterministic Gates (B2)**: Pure functional pipeline (G1-G9) guarantees no prompt injections, unauthorized writes, or schema violations enter the DB.
- **Fail-Closed Audit Log (INV-7)**: Every decision is recorded with a fixed reason code.
- **Human-in-the-Loop Queue (INV-5)**: Privileged memory lanes (`identity`, `authorization`, `procedural`) are sent to a pending queue for approval.
- **Asynchronous Digestion (INV-3)**: Memory writes never block on LLM generation.
- **Stdlib-only Core (INV-2)**: The core pipeline (`memory_core.*`) requires no 3rd-party dependencies, guaranteeing maximum portability.

## Installation

```bash
# Core only (no LLM adapters)
pip install .

# With OpenAI adapter
pip install .[openai]
```

## CLI Usage

The `memory-cli` command is provided for interacting with namespaces.

```bash
# Initialize a database for a namespace
memory-cli init my_agent

# Get the absolute path to the database
memory-cli db path my_agent

# Run the background consolidator loop (requires OPENAI_API_KEY)
memory-cli run my_agent --api-key sk-...

# Manage the proposal queue
memory-cli queue ls my_agent
memory-cli queue approve my_agent prop_123
memory-cli queue reject my_agent prop_123

# Tail the audit log
memory-cli audit my_agent -n 20
```

## Architecture

- **Block 1 (B1): The Vault**: Storage router, schema initialization, models.
- **Block 2 (B2): The Gates**: Deterministic pipeline, audit log, proposal queue.
- **Block 3 (B3): The Engine**: Consolidator run loop.
- **Block 4 (B4): The Context**: Narrative layer, injection formatting, OpenAI adapter.
- **Block 5 (B5): The Shell**: Packaging and CLI.

See the full [master specification](memory-core-v2-master-spec.md) for detailed invariant definitions and schemas.
