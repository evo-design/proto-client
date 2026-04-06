# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`proto-client` is a Python SDK for the Proto Bio API. It provides sync (`ProtoClient`) and async (`AsyncProtoClient`) clients with two namespaces: **tools** (bioinformatics tool execution) and **runs** (experiment optimization runs).

## Setup

```bash
uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
```

## Commands

```bash
make check          # Run all checks (lint + typecheck + test)
make test           # pytest with 80% coverage minimum
make lint           # ruff check + format validation
make typecheck      # mypy strict

# Raw equivalents
pytest                           # Run all tests
pytest tests/test_tools.py::test_name -x  # Single test
ruff check .                     # Lint
ruff format .                    # Format
mypy --strict proto_client       # Type check

# Regenerate sync runs code from async source
python scripts/gen_sync.py
```

## Architecture

### Async-First Code Generation

The async code in `proto_client/_async/` is the **source of truth**. The sync `proto_client/runs.py` is **auto-generated** from `_async/runs.py` via `scripts/gen_sync.py` (uses `unasync` for token-level transforms). CI verifies sync stays in sync with async.

**When editing runs logic**: modify `_async/runs.py`, then run `python scripts/gen_sync.py`. Never edit `runs.py` directly. CI runs `gen_sync.py` and checks `git diff --exit-code` to enforce this.

Only files in the `SYNC_TARGETS` list in `scripts/gen_sync.py` are transformed. Currently that's just `runs.py`. If adding a new async namespace to `_async/`, add it to `SYNC_TARGETS`.

**Exception**: `tools.py` and `_async/tools.py` are **both hand-written** (they intentionally diverge). Edit each independently.

### Client → Namespace → HTTP Stack

```
ProtoClient / AsyncProtoClient
├── .tools  → ToolsNamespace      (base: proto-tools.evodesign.org)
└── .runs   → RunsNamespace       (base: proto-language.evodesign.org)
              ↓
         httpx.Client / AsyncClient
              ↓
         RetryTransport / AsyncRetryTransport  (_http.py)
              └── exponential backoff + jitter, Retry-After support
```

Each namespace wraps an httpx client. The client manages two separate httpx clients (one per base URL). All endpoints return Pydantic-validated models from `models.py`.

### Error Hierarchy

`errors.py` maps HTTP status codes to typed exceptions via `from_response()`:

- `ProtoAPIError` (base) → `ProtoAuthError` (401/403), `ProtoNotFoundError` (404), `ProtoConflictError` (409), `ProtoValidationError` (422), `ProtoRateLimitError` (429), `ProtoServerError` (5xx)
- `RunFailedError` / `RunCancelledError` — raised by polling convenience methods

### Retry Logic

`_http.py` implements transport-level retries. Retryable: `{429, 500, 502, 503, 504}` + network/timeout errors. Client errors (400, 401, 403, 404, 409, 422) are never retried. Default: 2 retries, 0.5s initial delay, exponential backoff with jitter.

## Configuration

- **Env vars**: `PROTO_API_KEY`, `PROTO_TOOLS_BASE_URL`, `PROTO_RUNS_BASE_URL`
- **Defaults**: tools → `https://proto-tools.evodesign.org`, runs → `https://proto-language.evodesign.org`

## Testing Patterns

- Tests use `httpx.MockTransport` with request handler functions for integration-style tests
- `tests/helpers.py` provides `mock_response()`, `job_payload()`, `run_response_json()`, `make_async_ns()`, `make_sync_ns()` builders
- `monkeypatch` is used to mock `time.sleep` / `asyncio.sleep` in polling tests
- `asyncio_mode = "auto"` — async tests are discovered automatically
- Coverage excludes `_async/*` (auto-generated sync code is measured instead)

## Coding Conventions

- **Line length**: 120
- **Linter/formatter**: ruff (comprehensive rule set)
- **Type checking**: mypy strict mode
- **Docstrings**: Google style
- **Python**: 3.10+ type hint syntax — do **not** use `from __future__ import annotations`
- **Models**: Pydantic v2 with `ConfigDict(frozen=True)` on all response models
- **Logging**: `logging.getLogger(__name__)`, never `print()`
