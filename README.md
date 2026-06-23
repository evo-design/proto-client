# Proto Client

![Proto Client](https://proto-bio.github.io/proto-assets/covers/open-wings-code/carousel.png)

[![Checks](https://github.com/evo-design/proto-client/actions/workflows/checks.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/checks.yml)
[![Unit Tests](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml)
`proto-client` is the official Python SDK for the Proto project. Run any of **80+ bioinformatics tools** from [proto-tools](https://github.com/evo-design/proto-tools), submit **optimization runs** built with [proto-language](https://github.com/evo-design/proto-language), stream logs, and download results, all from a few lines of typed Python.

The SDK provides a synchronous `ProtoClient` and an asynchronous `AsyncProtoClient` with the same surface, fully type-checked responses, and transport-level retries. It also includes an **MCP server**, so Claude, Cursor, VS Code Copilot, and any other MCP-compatible agent can call the same APIs through natural language.

## Installation

All you need is Python 3.10+ and pip:

```bash
pip install proto-client
```

The MCP server is an optional extra:

```bash
pip install proto-client[mcp]
```

## Quickstart

Set `PROTO_API_KEY` in your environment (or pass `api_key=` explicitly), then:

```python
from proto_client import ProtoClient

client = ProtoClient()

# Run a bioinformatics tool and poll to completion (tools API)
job = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})

# Submit an optimization run and poll to completion (runs API)
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

Large cloud outputs (structures, logits, PAE matrices, embeddings) come back as `AssetRef` objects rather than inline JSON; the `client.assets` namespace downloads, decodes, or streams them to disk on demand. See [**Working with output assets**](https://github.com/evo-design/proto-client/blob/main/docs/mcp.md#working-with-output-assets) for the methods, MIME decoding, and examples.

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

For a single asset rather than the whole bundle, use `client.assets.download(ref, path)`. Both export routes have async equivalents: `await client.export_program(...)` and `await client.runs.export(...)`.

## Command line

A minimal `proto-client` CLI submits tools and optimization runs from a shell or CI, then writes the result JSON and downloads any output assets:

```bash
proto-client me                                                    # workspace and credits
proto-client tools run esmfold-prediction --inputs in.json --assets ./out
proto-client runs submit program.json --wait --export out.zip
```

See the [**CLI guide**](https://github.com/evo-design/proto-client/blob/main/docs/cli.md) for the full command reference.

## Using with AI agents (MCP)

`proto-client` includes an [MCP](https://modelcontextprotocol.io/) server so Claude, Claude Desktop, Cursor, VS Code Copilot, Codex, Gemini, and any other MCP-compatible agent can call the Proto Bio APIs through natural language. Connect to the **hosted** endpoint (nothing to install).

See the [**MCP user guide**](https://github.com/evo-design/proto-client/blob/main/docs/mcp.md) for per-agent connection snippets, the tool/prompt/resource surface, and a guided walkthrough.
