# Command Line Interface (CLI)

The `memory-cli` tool provides a direct interface for developers and system administrators to manage namespaces, review pending proposals, and trigger background consolidation.

## Global Options
*(Note: Current global configuration is handled via `Config` environment variables).*
- `MEMORY_CORE_DB_DIR`: Set the root directory for SQLite files (default: `~/.memory-core`).

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
Approves a specific proposal ID, moving it from the queue into the active `facts` table, and marking the audit log as `SUCCESS (APPROVED)`.

```bash
memory-cli queue approve <namespace> <proposal_id>
```

#### `queue reject`
Rejects a specific proposal ID, removing it from the queue and marking the audit log as `REJECTED_HUMAN`.

```bash
memory-cli queue reject <namespace> <proposal_id>
```

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
