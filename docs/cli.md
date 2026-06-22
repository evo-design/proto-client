# Using the Proto Bio command-line client

`proto-client` includes a small command-line client for submitting jobs from a shell or CI — run a bioinformatics tool, submit an optimization run, export results, and check your workspace. It deals only in JSON and files; discovery, typed validation, and human-readable formatting are intentionally left to proto-tools and the [MCP server](mcp.md).

Installing the package puts `proto-client` on your `PATH`:

```bash
pip install proto-client
```

## Authentication

Every command authenticates with your Proto API key. Set it in the environment:

```bash
export PROTO_API_KEY="your-api-key"
```

Or pass `--api-key` on any command to override it.

## Commands

### `me` — check your workspace

```bash
proto-client me
```

Prints the calling key's workspace, tier, scopes, and remaining credits.

### `tools example` — print a tool's example input

```bash
proto-client tools example esmfold-prediction > in.json
```

Writes a tool's minimal valid input JSON to stdout (or `-o FILE`). Use it as the starting point for `tools run`.

### `tools run` — run a bioinformatics tool

```bash
proto-client tools run esmfold-prediction --inputs in.json -o result.json --assets ./out
```

Submits a tool job, polls to completion, and writes the result JSON.

| Flag | Purpose |
|---|---|
| `--inputs FILE` | JSON inputs (required; `-` reads stdin) |
| `--config FILE` | Optional JSON tool config |
| `-o, --output FILE` | Write result JSON here (default: stdout) |
| `--assets DIR` | Download output assets into this directory, rewriting each `AssetRef` in the result to its local path |

### `runs submit` — submit an optimization run

```bash
# Create, execute, poll to completion, and write the results zip
proto-client runs submit program.json --wait --export out.zip

# Create and start the run, then print its id and return immediately
proto-client runs submit program.json

# Create the run idle, without starting any stages
proto-client runs submit program.json --no-execute
```

| Flag | Purpose |
|---|---|
| `--wait` | Poll until the run reaches a terminal state |
| `--no-execute` | Create the run idle (do not start stages) |
| `--export FILE` | With `--wait`, write the results zip here |
| `-o, --output FILE` | With `--wait`, write the run JSON here (default: stdout) |

Without `--wait`, the command prints the new `run_id` and returns. `--export` requires `--wait`.

### `runs status` — inspect a run

```bash
proto-client runs status run_123 -o status.json
```

Emits the run's current status and stage results as JSON.

### `runs export` — download a run's results

```bash
proto-client runs export run_123 out.zip
```

Downloads the results zip and prints its on-disk path. The destination path is optional and defaults to the server-provided filename in the current directory.

### `mcp` — launch the MCP server

```bash
proto-client mcp                                  # stdio (default)
proto-client mcp --transport http --port 9300     # HTTP
```

Launches the MCP server for AI agents. Requires the `[mcp]` extra (`pip install proto-client[mcp]`). See the [MCP user guide](mcp.md) for connecting agents.

## Output and exit behavior

- Results are emitted as JSON — to stdout, or to the path given by `-o/--output` (that path is echoed to stderr). Binary outputs download only when you pass `--assets DIR`.
- Cloud jobs poll until the server-guaranteed terminal state; the CLI never abandons a still-running job (there is no client-side timeout).
- Commands return `0` on success, `1` on API or I/O errors, `2` on invalid flag combinations, and `130` on interrupt.

Run `proto-client --help` (or `proto-client <command> --help`) for the full command tree.
