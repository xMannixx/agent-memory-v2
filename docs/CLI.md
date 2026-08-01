# Command Line Interface (CLI)

The `memory-cli` tool provides a direct interface for developers and system administrators to manage namespaces, review pending proposals, and trigger background consolidation.

## Global Options

Configuration is loaded via `load_config()` with the following precedence (highest wins): Environment variables → JSON config file → Defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_CORE_STORAGE_DATA_DIR` | `~/.memory-core` | Root directory for SQLite files |
| `MEMORY_CORE_STORAGE_MODE` | `single` | `single` (one DB) or `per-namespace` |
| `MEMORY_CORE_CONFIG` | — | Explicit path to a JSON config file |
| `MEMORY_CORE_CONSOLIDATOR_MAX_EPISODES_PER_RUN` | `200` | Max episodes per consolidation run |
| `MEMORY_CORE_CONSOLIDATOR_MAX_NEW_FACTS_PER_RUN` | `20` | Budget: max new facts committed per run |
| `MEMORY_CORE_CONSOLIDATOR_REVIEW_TTL_DAYS` | `14` | Days before pending proposals expire |
| `MEMORY_CORE_NARRATIVE_MAX_CHARS` | `2000` | Max characters for narratives |
| `MEMORY_CORE_NARRATIVE_REVIEW` | `false` | Require human review for narratives |

## Commands

### `init`
Initializes the database schema for a specific namespace. This is fully idempotent.

```bash
memory-cli init <namespace>
```
**Example**: `memory-cli init agent_alice`

---

### `db path`
Returns the absolute path to the SQLite database file for the given namespace. Useful for opening the DB in tools like `sqlite3` or DBeaver.

```bash
memory-cli db path <namespace>
```
**Example**: `memory-cli db path agent_alice`

---

### `queue`
Manages the `proposal_queue` for human-gated memory updates.

#### `queue ls`
Lists all pending memory proposals for a namespace that require human review.

```bash
memory-cli queue ls <namespace>
```

#### `queue approve`
Approves a proposal and atomically commits its payload (fact, supersede, or narrative) to the database. The status flip, data write, and audit entry happen within a single SQLite transaction.

```bash
memory-cli queue approve <namespace> <proposal_id> [--by <operator>]
```

- `--by`: Operator identity for the audit trail (defaults to `$USER` or `cli`).

#### `queue reject`
Marks the proposal as rejected and records the decision in the audit log. It is not deleted, preserving the audit trail.

```bash
memory-cli queue reject <namespace> <proposal_id> [--by <operator>]
```

- `--by`: Operator identity for the audit trail (defaults to `$USER` or `cli`).

---

### `audit`
Tails the immutable audit log for a namespace. This shows every action taken by the Gate Pipeline, including reasons for rejection (e.g., `REJECTED_SCHEMA`, `REJECTED_INJECTION`).

```bash
memory-cli audit <namespace> [--lines N]
```
**Example**: `memory-cli audit agent_alice -n 20`

---

### `run`
Triggers the asynchronous Consolidator engine manually. It will fetch unconsumed episodes, call the LLM, and push the results through the Gate Pipeline.

*Requires the `[openai]` extra package to be installed, and an OpenAI API key.*

```bash
memory-cli run <namespace> --api-key <key>
```
Alternatively, set the `OPENAI_API_KEY` environment variable:
```bash
export OPENAI_API_KEY="sk-..."
memory-cli run <namespace>
```
