---
name: memory-core-v2
description: "Use when integrating Agent Memory Core v2 with an LLM agent or reviewing its deterministic memory gates."
version: 2.0.0-dev
author: xPerryx + Lena OpenClaw
license: MIT
platforms: [linux, macos, windows]
---

# Memory Core v2

Local-first, framework-agnostic long-term memory for LLM agents (Hermes,
OpenClaw, and compatible hosts).  A strict deterministic gate pipeline
prevents LLM hallucinations, prompt injections, and schema violations from
entering the memory store.

## Features

- **G1–G9 Gate Pipeline** — pure-functional, fail-closed, LLM-free validation
- **Human-in-the-Loop Queue** — privileged lanes route to a `proposal_queue`
  for human approval; approvals atomically commit facts
- **Append-only Audit Log** — every decision recorded with a strict reason code
- **Asynchronous Consolidator** — background digestion of episodes into facts
- **Namespace Isolation** — per-namespace or single-file SQLite topologies
- **Zero Dependencies** — core pipeline uses only the Python Standard Library
- **CLI** (`memory-cli`) — init, db path, queue ls/approve/reject, audit, run

## Status

- [x] B1: Skeleton, config, schema, storage, episodes, migration
- [x] B2: Gate pipeline (G1–G9), proposal queue, audit
- [x] B3: Consolidator run loop, LLM backends
- [x] B4: Narrative layer, injection, adapters
- [x] B5: CLI, packaging, docs

## Quick Reference

```bash
# Initialize
memory-cli init my_agent

# Run consolidator
OPENAI_API_KEY="sk-..." memory-cli run my_agent

# Review proposals
memory-cli queue ls my_agent
memory-cli queue approve my_agent <id> --by admin

# Audit trail
memory-cli audit my_agent -n 20
```

See the [master specification](../../memory-core-v2-master-spec.md) for full
documentation.
