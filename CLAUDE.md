# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`proto-client` is a Python SDK for the Proto Bio API. It provides sync (`ProtoClient`) and async (`AsyncProtoClient`) clients with three namespaces: **tools** (bioinformatics tool execution), **runs** (experiment optimization runs), and **assets** (on-demand download/decode of large outputs returned as `AssetRef`s).

## Setup

```bash
uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
```

## Commands

```bash
pytest                           # Run all tests (branch coverage enforced; threshold in pyproject.toml)
pytest tests/test_tools.py::test_name -x  # Single test
ruff check . && ruff format --check .     # Lint
mypy --strict proto_client               # Type check

# Regenerate sync runs code from async source
python scripts/gen_sync.py
```

## Architecture

### Async-First Code Generation

The async code in `proto_client/_async/` is the **source of truth**. The sync `proto_client/runs.py` and `proto_client/_ndjson.py` are **auto-generated** from their `_async/` sources via `scripts/gen_sync.py` (uses `unasync` for token-level transforms). CI verifies the generated files stay in sync with their async sources.

**When editing a generated module**: modify the `_async/` source, then run `python scripts/gen_sync.py`. Never edit the generated `runs.py` / `_ndjson.py` directly. CI runs `gen_sync.py` and checks `git diff --exit-code` on both to enforce this.

Only files in the `SYNC_TARGETS` list in `scripts/gen_sync.py` are transformed. Currently those are `_ndjson.py` and `runs.py`. If adding a new async namespace to `_async/`, add it to `SYNC_TARGETS`.

**Exception**: `client.py`, `tools.py`, and `assets.py` (with their `_async/` counterparts) are **hand-written on both sides** — they intentionally diverge, so they're kept out of `SYNC_TARGETS`. Edit each independently.

### Client → Namespace → HTTP Stack

```
ProtoClient / AsyncProtoClient
├── .tools   → ToolsNamespace     (base: resolved TOOLS_BASE_URL)
├── .runs    → RunsNamespace      (base: resolved RUNS_BASE_URL)
└── .assets  → AssetsNamespace    (holds both clients; downloads AssetRef bytes from either service)
              ↓
         httpx.Client / AsyncClient
              ↓
         RetryTransport / AsyncRetryTransport  (utils/http.py)
              └── exponential backoff + jitter, Retry-After support
```

`tools` and `runs` each wrap one of two httpx clients (one per base URL); `assets` holds both so it can resolve a ref from whichever service produced it. All endpoints return Pydantic-validated models from `models.py`.

### Error Hierarchy

`errors.py` maps HTTP status codes to typed exceptions via `from_response()`:

- `ProtoAPIError` (base) → `ProtoAuthError` (401/403), `ProtoNotFoundError` (404), `ProtoConflictError` (409), `ProtoValidationError` (422), `ProtoRateLimitError` (429), `ProtoServerError` (5xx)
- `RunFailedError` / `RunCancelledError` — raised by polling convenience methods

### MCP Server

`proto_client/mcp/` is a FastMCP server exposing Proto Bio capabilities to AI agents. It wraps `AsyncProtoClient` and registers tools (bioinformatics tool discovery + execution, optimization-run management, and asset retrieval), plus MCP prompts and resources. The `instructions` block in `server.py` is the authoritative, always-current surface — don't re-enumerate the tool list here.

```bash
pip install proto-client[mcp]
python -m proto_client.mcp              # stdio transport (Claude Desktop/Code)
python -m proto_client.mcp --transport http --port 9300  # HTTP transport
```

The server lifespan creates/closes an `AsyncProtoClient` that reads config from env vars (`PROTO_API_KEY`, etc.). Tool handlers are thin wrappers that delegate to client methods and serialize Pydantic models to dicts.

### CLI

`proto_client/cli.py` is a minimal stdlib-`argparse` CLI for submitting jobs from a shell: `tools run`/`example`, `runs submit`/`status`/`export`, `me`, and `mcp` (which launches the server via `mcp/__main__.run_server`). Command functions are `cmd_*(client, args) -> int` taking an explicit client (same testability pattern as the MCP `*_impl`), dispatched through `args.func`. Output is JSON + downloaded assets only — no human formatting; typed validation and discovery deliberately stay in proto-tools/MCP. It submits via the same `ProtoClient`, so cloud jobs poll until the server-guaranteed terminal state (no client-side `--timeout`, which would only abandon a still-running cloud job).

Console scripts (`pyproject.toml`): `proto-client` (the CLI) and `proto-client-mcp` (back-compat alias for the server launcher).

### Retry Logic

`utils/http.py` implements transport-level retries. Retryable: `{429, 500, 502, 503, 504}` + network/timeout errors + `httpx.RemoteProtocolError` (server-side keep-alive disconnect on long polls). `LocalProtocolError` (client-side bug), `DecodingError`, and `InvalidURL` stay non-retriable. Client errors (400, 401, 403, 404, 409, 422) are never retried. Tuning lives in `RetryConfig` (`utils/http.py`): conservative defaults, exponential backoff with jitter, and an honored server `Retry-After` (429/503) capped at `retry_after_max`. Only idempotent methods retry unconditionally; a POST retries only with an `Idempotency-Key` (auto-generated by `tools.run`/`run_batch`; `runs` send none and are therefore never retried).

## Configuration

- **Env vars**: `PROTO_API_KEY` (auth); `PROTO_TOOLS_BASE_URL` / `PROTO_RUNS_BASE_URL` (override per-service endpoints); `PROTO_LOG=debug|info` (enable SDK logging)
- **Defaults & base-URL resolution** (`explicit arg → env var → packaged default`, https enforced off loopback): see `proto_client/utils/defaults.py`

## Testing Patterns

- Tests use `httpx.MockTransport` with request handler functions for integration-style tests
- `tests/helpers.py` provides `mock_response()`, `job_payload()`, `run_response_json()`, `make_async_ns()`, `make_sync_ns()` builders
- `monkeypatch` is used to mock `time.sleep` / `asyncio.sleep` in polling tests
- `asyncio_mode = "auto"` — async tests are discovered automatically
- Coverage excludes `_async/*` (auto-generated sync code is measured instead)

## Coding Conventions

- **Linter/formatter**: ruff (line length and full rule set in `pyproject.toml`)
- **Type checking**: mypy strict mode
- **Docstrings**: Google style
- **Python**: 3.10+ type hint syntax — do **not** use `from __future__ import annotations`
- **Models**: Pydantic v2 with `ConfigDict(frozen=True)` on all response models
- **Logging**: `logging.getLogger(__name__)`, never `print()`
