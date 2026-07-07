<div align="center">
  <h1>🧠 Agent Memory Core v2</h1>
  <p><strong>A deterministic, standard-library-only long-term memory engine for autonomous AI agents.</strong></p>
  
  [![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
  [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
  [![Tests](https://img.shields.io/badge/tests-144%20passed-brightgreen.svg)]()
</div>

<hr/>

Memory Core v2 solves the "hallucination and corruption" problem in agentic memory by placing a strict, deterministic, and impenetrable **Gate Pipeline** in front of the database. 

Instead of letting an LLM write raw SQL or manipulate JSON files directly, the LLM acts merely as an asynchronous *proposer*. Every proposal is strictly validated against schemas, budgets, and security policies before it is ever committed.

## 🌟 Key Features

* **Strictly Deterministic Gates**: A pure functional, LLM-free pipeline (Gates 1-9) guarantees that no prompt injections, unauthorized writes, or schema violations enter the system.
* **Append-Only Audit Trail**: Every accepted and rejected proposal is logged with a strict reason code. The system is 100% fail-closed.
* **Human-in-the-Loop Queue**: Highly privileged memory lanes (like `identity` or `procedural_rules`) cannot be altered by the LLM alone. They are routed to a pending `proposal_queue` for human administrator approval.
* **Asynchronous Digestion**: Memory ingestion (writing raw episodes/conversations) never blocks on the LLM. The LLM runs as a decoupled background worker (the "Consolidator").
* **Maximum Portability (Zero Dependencies)**: The core pipeline is built strictly using the Python Standard Library. No `sqlalchemy`, no `pydantic`, no 3rd-party bloat.

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/xMannixx/agent-memory-v2.git
cd agent-memory-v2

# Install the core (Zero dependencies)
pip install .

# Install with the official OpenAI adapter
pip install .[openai]
```

## 🚀 Quickstart

### 1. Initialize a Memory Namespace
Namespaces isolate memory for different users, agents, or sessions.

```bash
memory-cli init my_agent
```

### 2. Run the Consolidator Loop
Trigger the background engine to digest unconsumed episodes into structured facts.
*(Requires the `[openai]` extra and an API key).*

```bash
export OPENAI_API_KEY="sk-..."
memory-cli run my_agent
```

### 3. Review the Proposal Queue
If the LLM proposed updates to privileged lanes (e.g., identity facts), review and approve them.

```bash
memory-cli queue ls my_agent
memory-cli queue approve my_agent prop_1234abcd
```

### 4. Inspect the Audit Log
See exactly what the Gate Pipeline did behind the scenes.

```bash
memory-cli audit my_agent -n 10
```

## 📚 Documentation

Dive deeper into how Memory Core v2 works:

- [Architecture Overview](docs/ARCHITECTURE.md) - Deep dive into the 5 core blocks and the Gate Pipeline.
- [CLI Reference](docs/CLI.md) - Detailed guide to the `memory-cli`.
- [Contributing](CONTRIBUTING.md) - How to run the test suite and maintain the system invariants.

## 🏗 Architecture at a Glance

Memory Core v2 is built in 5 strictly decoupled blocks:
1. **The Vault (B1)**: The SQLite storage engine, schema initialization, and multi-tenant routing.
2. **The Gates (B2)**: The immune system. 9 deterministic evaluation gates for incoming memory proposals.
3. **The Engine (B3)**: The asynchronous `Consolidator` run loop.
4. **The Context (B4)**: The Narrative layer and dynamic injection adapters for the host LLM prompt.
5. **The Shell (B5)**: The packaging structure and the CLI.

---
*Built for the Agent Memory Skill framework.*
