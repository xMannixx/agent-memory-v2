# Contributing to Memory Core v2

We welcome contributions! However, because Memory Core v2 is designed as a mission-critical security layer (the "Immune System" for agent memory), we have extremely strict engineering invariants. 

Please read this document carefully before submitting a Pull Request.

## 1. The Core Invariants

If your PR breaks an invariant, the test suite will fail. If the test suite passes but violates the spirit of an invariant, the PR will be rejected.

- **INV-1 (Determinism)**: The Core Pipeline MUST be pure and deterministic. Given the same DB state and the same JSON inputs, the gates must output the exact same DB state. Do not use random numbers, non-seeded hashes, or non-injected timestamps in the core evaluation paths.
- **INV-2 (Standard Library Only)**: `src/` (excluding `src/adapters/`) must NOT import any third-party libraries. No `sqlalchemy`, no `pydantic`. This ensures the core is incredibly fast and highly portable.
- **INV-3 (Asynchronous Bounds)**: Do not add any blocking LLM calls to the synchronous read/write paths. The Consolidator runs in the background.

## 2. Development Setup

1. Fork and clone the repository.
2. We highly recommend using a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the package in editable mode with test dependencies (assuming you are installing `pytest`):
   ```bash
   pip install -e .
   pip install pytest
   ```

## 3. Running the Test Suite

The test suite is extensive (150+ tests) and enforces invariants strictly via metaprogramming (`test_invariants.py`).

Run the suite using `pytest`:
```bash
pytest tests/ -v
```

If you add a new module to the `src/` core, you **must** add it to the `CORE_MODULES` list in `tests/test_invariants.py` to ensure it passes the `INV-2` (stdlib-only) check.

## 4. Adapters

If you want to add support for a new LLM provider (e.g., Anthropic, Gemini, local Ollama):
1. Create your adapter in `src/adapters/`.
2. Inherit from `src.llm.LLMProvider`.
3. You **are** allowed to use third-party libraries (like `anthropic` or `google-generativeai`) inside the `adapters/` folder. The INV-2 tests explicitly ignore this folder.
4. Add the adapter as an optional dependency group in `pyproject.toml`.

## 5. Submitting a Pull Request

1. Ensure all tests pass (`pytest`).
2. Add a summary of your changes to `CHANGELOG.md` under the `[Unreleased]` section.
3. Submit the PR with a clear description of the problem solved.
