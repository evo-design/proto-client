[![Checks](https://github.com/evo-design/proto-client/actions/workflows/checks.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/checks.yml)
[![Unit Tests](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/evs3Unkegv)

# proto-client

Python SDK for Proto Bio APIs.

## Related Repositories

- [`proto-language`](https://github.com/evo-design/proto-language) – Core language framework (constraints, generators, optimizers)
- [`proto-tools`](https://github.com/evo-design/proto-tools) – Bioinformatics tool wrappers with isolated environments

## Installation

```bash
pip install proto-client
```

## Usage

```python
from proto_client import ProtoClient

client = ProtoClient(api_key="...")

# Run a tool (the tools API)
result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})

# Submit an optimization run and poll to completion (the runs API)
run = client.runs.run(program_data={...})
```

### Async

```python
from proto_client import AsyncProtoClient

async with AsyncProtoClient(api_key="...") as client:
    run = await client.runs.create(program_data={...})
    status = await client.runs.get(run["run_id"])
```

Set `PROTO_API_KEY` to skip passing `api_key=` each time.

### Working with output assets

Large cloud outputs can be returned as `AssetRef` objects instead of inline
strings or JSON arrays. The SDK asset helpers work with API-readable refs:
an `AssetRef` object or raw dict that includes a `url` pointing back to one of
the configured Proto API origins. They are intended for `kind="output"` refs
returned in tool-job or run results.

Not every `AssetRef` is fetchable: upload allocation refs, reference database
refs without an API-readable URL, refs missing `url`, and non-Proto URLs are
rejected. The client fetches through authenticated Proto API origins and strips
authentication headers before following any redirect away from those origins.

| Method | Return value | MIME handling | Use when |
|---|---|---|---|
| `client.assets.download(ref, path)` | bytes streamed to a file | none; preserves exact stored bytes | you want a file, or the asset may be large |
| `client.assets.get(ref)` | raw `bytes` in memory | none; preserves exact stored bytes | you explicitly want raw bytes |
| `client.assets.decode(ref)` | Python object, text, or bytes | decodes by `mime_type` | you want a convenient in-Python value |

`decode()` maps `application/json+gzip` to gunzipped JSON,
`application/json` / `*+json` to JSON, `chemical/*` / `text/*` to UTF-8 text,
and unknown MIME types to raw bytes. It loads the full asset into memory, so
prefer `download()` for large logits, PAE matrices, embeddings, and other dense
outputs.

Typed tool output validation stays lazy. If an output model declares an
`AssetRef` field, validation preserves the ref. If it declares the old raw
shape, such as `list[list[float]]`, validation fails normally; the SDK does not
silently download large assets during validation.

```python
from proto_client import ProtoClient

client = ProtoClient(api_key="...")

job = client.tools.run("evo2-score", inputs, config)
logits_ref = job.result["scores"][0]["logits"]
client.assets.download(logits_ref, "logits.json.gz")

run = client.runs.get("run_123")
pdb_output = run.stage_results[0].results[0].constructs[0].segments[0].constraints["fold"].data[
    "pdb_output"
]
pdb_text = client.assets.decode(pdb_output)
```

Async clients expose the same namespace with `await`:

```python
async with AsyncProtoClient(api_key="...") as client:
    pdb_text = await client.assets.decode(pdb_output)
```

### Exporting a run's results to a folder

There are two routes depending on where the program ran:

| Where the program ran | Use | What you get |
|---|---|---|
| Locally in Python (`program.run()`) with maybe-cloud tool dispatches | `client.export_program(program, "out/")` | Folder with 4 CSV tables + `sequences.fasta` + `assets/`; writes local `seq.structure` / `seq.logits` from the in-memory program and downloads any AssetRefs found in metadata |
| On the server (submitted via `client.runs.create(...)`) | `client.runs.export(run_id, "out.zip")` | Server-built zip with 4 CSV tables + FASTA + `program.json` + `manifest.json` + `assets/` |

The two cover non-overlapping data. The local route needs the live `Program` object (because `seq.structure` / `seq.logits` only exist client-side). The server route needs a `run_id` (because the results live in the API database). Pick by which one you have.

```python
# Local Program (proto-language installed alongside proto-client)
program = Program(...)
program.run()
client.export_program(program, "out/")

# Server-side Run
run = client.runs.run(program_data=...)  # creates and polls to terminal status
client.runs.export(run.id, "out.zip")
```

For per-asset downloads (when you just want one PDB, not the whole bundle), use `client.assets.download(ref, path)` or `ref.resolve()`.

## Using with AI Agents (MCP)

Proto Bio exposes an [MCP](https://modelcontextprotocol.io/) server that works with Claude, OpenAI, VS Code Copilot, Cursor, ChatGPT, and any MCP-compatible client.

```bash
pip install proto-client[mcp]
```

Add to your MCP client config (`.mcp.json`, `claude_desktop_config.json`, etc.):

```json
{
  "mcpServers": {
    "proto-bio": {
      "command": "python",
      "args": ["-m", "proto_client.mcp"],
      "env": { "PROTO_API_KEY": "your-api-key" }
    }
  }
}
```

The server exposes tools for bioinformatics tool discovery and execution (`list_tools`, `search_tools`, `get_tool_schema`, `run_tool`) and optimization run management (`list_components`, `validate_program`, `create_run`, `get_run_status`, `cancel_run`, `get_run_results`).

A `proto-client-mcp` CLI script is also installed:

```bash
proto-client-mcp                                       # stdio (default)
proto-client-mcp --transport http --port 9300           # HTTP
```

## Development: async-first with unasync

`AsyncRunsNamespace` (in `proto_client/_async/runs.py`) is the source of
truth. The sync `RunsNamespace` (`proto_client/runs.py`) is **generated**
from it via [unasync](https://github.com/python-trio/unasync) — a
token-level transform configured in `scripts/gen_sync.py`. The generated
file is committed to the repo, and a CI check verifies it stays in sync.
To regenerate manually:

```bash
python scripts/gen_sync.py
```

Do not edit `proto_client/runs.py` directly — your changes will be
overwritten on the next regen.
