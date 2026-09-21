# AGENTS.md

Python 3.12+ framework for a panel of LLMs that deliberate until consensus. This repo implements only **Phase 0 (Skeleton)**: `pllmenary.config`, `pllmenary.messages`, `pllmenary.models` (protocols only), and `pllmenary.testing.mock`. The conversational loop, adapters, and runtimes are future phases. The authoritative design is an **external spec**, cited per-feature in docstrings (`Spec: X`, `Spec-plan: X`) — it is not in this repo. Do not implement behavior beyond the phase implied by a file's docstrings.

## Commands

- Install: `pip install -e ".[dev]"` (README + CI). `uv.lock` is present but the existing `.venv` has base deps only — pytest is NOT installed there; run `uv sync --extra dev` first if you use uv.
- Test: `pytest` (single file: `pytest tests/test_mock_provider.py`). `testpaths = ["tests"]`, `asyncio_mode = "auto"` (async tests run without needing `@pytest.mark.asyncio`).
- No lint, format, or typecheck tooling is configured. Do not invent one.

## Architecture & conventions

- src layout, `hatchling` build backend, package at `src/pllmenary`. Only dependency: `pydantic>=2,<3`.
- Every data type crossing the model-protocol boundary is a **frozen** Pydantic model (`ConfigDict(frozen=True)`): values must stay immutable and picklable because multiprocess mode pickles them across processes. Preserve this for any new types. `from __future__ import annotations` + full annotations throughout.
- `Model`/`Provider` in `models.py` are `Protocol`s; concrete adapters implement them. A provider registers itself as a `provider(ref: ModelRef) -> Provider` function reachable by dotted path (e.g. `pllmenary.testing.mock:provider`).
- All model-call failures must be raised as `ModelError` classified `transient`/`timeout`/`permanent` — never plain exceptions.
- `ModelRef.settings` holds credential variable *names* and adapter settings, never secrets.
- Mock provider (`testing/mock.py`): `ModelRef.settings["script"]` selects a `Script` either by key in the provider's `scripts` dict or via `module:attr` import path. Rule `limit` use-counts are **process-local**, so fail-then-succeed scenarios are only deterministic within one process.
- Build a valid `Config` in tests via `make_config(**overrides)` from `tests/conftest.py` (roles/loop/budgets/infrastructure are all required, no defaults at top level).