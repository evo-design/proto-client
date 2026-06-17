# 🧬 Proto Client 🐍

![Proto Client](https://proto-bio.github.io/proto-assets/default/hero.png)

[![Checks](https://github.com/evo-design/proto-client/actions/workflows/checks.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/checks.yml)
[![Unit Tests](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml)
`proto-client` is the official Python SDK for the **Proto Bio APIs**. Run any of **60+ bioinformatics tools**, submit **optimization runs**, stream logs, and download results, all from a few lines of typed Python.

The SDK ships a synchronous `ProtoClient` and an asynchronous `AsyncProtoClient` with the same surface, fully type-checked responses, and transport-level retries. It also bundles an **MCP server**, so Claude, Cursor, VS Code Copilot, and any other MCP-compatible agent can drive the same APIs through natural language.

## Related Repositories

- [`proto-language`](https://github.com/evo-design/proto-language) – High-level programming language for generative biology
- [`proto-tools`](https://github.com/evo-design/proto-tools) – Bioinformatics tool wrappers with isolated environments

## Installation

All you need is Python 3.10+ and pip:

```bash
pip install proto-client
```

For the MCP server, install the optional extra:

```bash
pip install proto-client[mcp]
```

## Quickstart

Set `PROTO_API_KEY` in your environment (or pass `api_key=` explicitly), then:

```python
from proto_client import ProtoClient

client = ProtoClient()

# Run a bioinformatics tool and poll to completion (the tools API)
job = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})

# Submit an optimization run and poll to completion (the runs API)
run = client.runs.run(program_data={...})
```

### Async

Every namespace has an identical async surface. `await` the calls and use the client as an async context manager:

```python
from proto_client import AsyncProtoClient

async with AsyncProtoClient() as client:
    run = await client.runs.create(program_data={...})
    status = await client.runs.get(run.run_id)
```

## Working with output assets

Large cloud outputs (structures, logits, PAE matrices, embeddings) come back as `AssetRef` objects rather than inline JSON. The `client.assets` namespace fetches their bytes on demand:

| Method | Return value | MIME handling | Use when |
|---|---|---|---|
| `client.assets.download(ref, path)` | bytes streamed to a file | none; preserves exact stored bytes | you want a file, or the asset may be large |
| `client.assets.get(ref)` | raw `bytes` in memory | none; preserves exact stored bytes | you explicitly want raw bytes |
| `client.assets.decode(ref)` | Python object, text, or bytes | decodes by `mime_type` | you want a convenient in-Python value |

`decode()` maps `application/json+gzip` to gunzipped JSON, `application/json` / `*+json` to JSON, and `chemical/*` / `text/*` to UTF-8 text; unknown MIME types stay raw bytes. It loads the full asset into memory, so prefer `download()` for large outputs.

```python
client = ProtoClient()

job = client.tools.run("evo2-score", inputs, config)
logits_ref = job.result["scores"][0]["logits"]
client.assets.download(logits_ref, "logits.json.gz")

run = client.runs.get("run_123")
# Per-constraint data lives on full timepoint rows, not the slim run summary.
tp = client.runs.get_timepoint(run.id, stage=0, timepoint=0)
pdb_output = tp.results[0].constructs[0].segments[0].constraints["fold"].data["pdb_output"]
pdb_text = client.assets.decode(pdb_output)
```

The client fetches only through authenticated Proto API origins, and strips authentication headers before following any redirect away from those origins. Not every ref is fetchable: upload-allocation refs, reference-database refs without an API-readable URL, and refs missing a `url` are rejected. Async clients expose the same namespace with `await`.

## Exporting a run's results

There are two export routes, depending on where the program ran:

| Where the program ran | Use | What you get |
|---|---|---|
| Locally in Python (`program.run()`) | `client.export_program(program, "out/")` | Folder with 4 CSV tables + `sequences.fasta` + `assets/`; writes local `seq.structure` / `seq.logits` and downloads any AssetRefs found in metadata |
| On the server (`client.runs.create(...)`) | `client.runs.export(run_id, "out.zip")` | Server-built zip with 4 CSV tables + FASTA + `program.json` + `manifest.json` + `assets/` |

The two cover non-overlapping data: the local route needs the live `Program` object (because `seq.structure` / `seq.logits` only exist client-side), the server route needs a `run_id` (because the results live in the API database). Pick by which one you have.

```python
# Local Program (proto-language installed alongside proto-client)
program = Program(...)
program.run()
client.export_program(program, "out/")

# Server-side Run
run = client.runs.run(program_data=...)  # creates and polls to terminal status
client.runs.export(run.id, "out.zip")
```

For a single asset rather than the whole bundle, use `client.assets.download(ref, path)`.

## Command line

A minimal `proto-client` CLI ships for submitting jobs from a shell or CI. Set `PROTO_API_KEY`, then:

```bash
# Scaffold a tool's inputs, then submit, wait, write the result, and download assets
proto-client tools example esmfold-prediction > in.json
proto-client tools run esmfold-prediction --inputs in.json -o result.json --assets ./out

# Submit an optimization run and export its results
proto-client runs submit program.json --wait --export out.zip

# Check the calling key's workspace and credits
proto-client me
```

Results are emitted as JSON (stdout or `-o FILE`); binary outputs download to `--assets DIR`. `proto-client mcp` launches the MCP server (below). Run `proto-client --help` for the full command tree.

## Using with AI agents (MCP)

Proto Bio ships an [MCP](https://modelcontextprotocol.io/) server that works with Claude, OpenAI, VS Code Copilot, Cursor, ChatGPT, and any MCP-compatible client.

```bash
pip install proto-client[mcp]
```

Add it to your MCP client config (`.mcp.json`, `claude_desktop_config.json`, etc.):

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

The server exposes `whoami` (workspace, scopes, and credits for the calling key), tools for bioinformatics tool discovery and execution (`list_tools`, `search_tools`, `get_tool_schema`, `get_tool_example`, `run_tool`), and optimization-run management (`list_components`, `validate_program`, `create_run`, `get_run_status`, `run_stage`, `cancel_run`, plus result retrieval via `get_run_metrics` / `get_run_timepoints`), alongside MCP prompts and resources. See the `instructions` block in `proto_client/mcp/server.py` for the authoritative, always-current surface.

A `proto-client-mcp` CLI script is installed alongside:

```bash
proto-client-mcp                                        # stdio (default)
proto-client-mcp --transport http --port 9300           # HTTP
```

## Development

The async modules in `proto_client/_async/` are the **source of truth**. Their sync mirrors (`proto_client/runs.py` and `proto_client/_ndjson.py`) are **generated** from them via [unasync](https://github.com/python-trio/unasync), a token-level transform configured in `scripts/gen_sync.py`. The generated files are committed, and a CI check verifies they stay in sync. To regenerate after editing an async source:

```bash
python scripts/gen_sync.py
```

Do not edit the generated sync files directly; your changes will be overwritten on the next regen. See [`CLAUDE.md`](CLAUDE.md) for the full architecture, conventions, and testing notes.
