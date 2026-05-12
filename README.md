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

### Downloading output assets

Large outputs are returned as `AssetRef` objects (dicts on the wire) carrying a
self-describing `url`. Use `client.assets.download()` for large files;
`get()` loads the full asset into memory. Both accept the raw dict pulled
straight out of a result — no manual validation step needed. One namespace
serves both tool-job and run outputs; routing happens automatically.

```python
from proto_client import ProtoClient

client = ProtoClient(api_key="...")

job = client.tools.run("evo2-score", inputs, config)
client.assets.download(job.result["scores"][0]["logits"], "logits.json.gz")

run = client.runs.get("run_123")
pdb_output = run.stage_results[0].results[0].constructs[0].segments[0].constraints["fold"].data[
    "pdb_output"
]
pdb_bytes = client.assets.get(pdb_output)
```

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
