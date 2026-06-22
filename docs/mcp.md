# Using the Proto Bio MCP server

Connect any MCP-compatible AI agent — Claude Code, Claude Desktop, Cursor, VS Code Copilot, Codex, Gemini — to Proto Bio, and run bioinformatics tools and sequence-optimization runs through natural language. The hosted server needs **nothing installed**: you point your agent at a URL and authenticate with your Proto API key.

## Prerequisites

- A **Proto Bio API key** from your workspace.

The key is passed as a **Bearer token**. The hosted server holds no key of its own, so every request authenticates as *you*; your key never lives on the server.

## 1. Connect

### Hosted (recommended — no install)

Point your agent at `https://mcp.evodesign.org/mcp` and authenticate with your Proto API key as a Bearer token. Each request uses the key in its own `Authorization` header.

**Claude Code:**

```bash
claude mcp add --transport http proto-bio https://mcp.evodesign.org/mcp \
  --header "Authorization: Bearer $PROTO_API_KEY"
```

**`.mcp.json` / Claude Desktop:**

```json
{
  "mcpServers": {
    "proto-bio": {
      "type": "http",
      "url": "https://mcp.evodesign.org/mcp",
      "headers": { "Authorization": "Bearer ${PROTO_API_KEY}" }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`) — same shape, but env interpolation uses `${env:PROTO_API_KEY}`.

**VS Code** (`.vscode/mcp.json`) — top-level key is `servers`, and secrets come from `inputs`:

```json
{
  "inputs": [{ "type": "promptString", "id": "proto-api-key", "description": "Proto API key", "password": true }],
  "servers": {
    "proto-bio": {
      "type": "http",
      "url": "https://mcp.evodesign.org/mcp",
      "headers": { "Authorization": "Bearer ${input:proto-api-key}" }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.proto-bio]
url = "https://mcp.evodesign.org/mcp"
bearer_token_env_var = "PROTO_API_KEY"
```

**Gemini CLI** (`~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "proto-bio": {
      "httpUrl": "https://mcp.evodesign.org/mcp",
      "headers": { "Authorization": "Bearer $PROTO_API_KEY" }
    }
  }
}
```

### Verify the connection

In a Claude Code session, run `/mcp`. You should see **proto-bio · Connected** with a tool count greater than zero. If it shows **0 tools** or **authentication failed**, your Bearer token is missing or wrong.

## 2. First call — confirm your key

Describe what you want in natural language; the agent picks the right tool. The cleanest first call confirms your key end to end:

> **You:** "Check my Proto workspace and remaining credits."
>
> → the agent calls **`whoami`** → returns your workspace, scopes, and credit balance.

## 3. Run a bioinformatics tool

The **tools** surface follows discover → inspect → run → fetch:

> **You:** "What Proto tools can predict protein structure?"
> → **`search_tools`** (or **`list_tools`**, filterable by category / GPU) → e.g. *ESMFold*.
>
> **You:** "Run ESMFold on this sequence: MKT…"
> → **`get_tool_schema`** (learns the required inputs) → **`run_tool`** with the tool key + inputs → returns the result. Large outputs (structures, files) come back as **asset references**.
>
> **You:** "Download the predicted structure."
> → **`fetch_asset`** → pulls the actual bytes.

New to a tool? The **`find_tool`** and **`tool_walkthrough`** prompts (below) guide discovery and first use.

## 4. Optimize a sequence

The **runs** surface drives design → validate → run → inspect:

> **You:** "Design a program to optimize this sequence for X."
> → browse the valid building blocks with **`list_components`** (constraints / generators / optimizers) and assemble the program JSON.
>
> → **`validate_program`** catches errors first → **`create_run`** → **`run_stage`** → poll **`get_run_status`**.
>
> **You:** "How is it converging?"
> → **`get_run_metrics`** (decimated chart series), or **`get_run_timepoints`** / **`get_run_timepoint`** for full per-step rows. **`cancel_run`** stops a run.

## 5. Tools, prompts, and resources

The server exposes three MCP surfaces:

- **Tools** — called automatically by the agent: `mcp__proto-bio__whoami`, `…__run_tool`, `…__create_run`, etc.
- **Prompts** — slash commands you invoke yourself:
  `/mcp__proto-bio__find_tool`, `…__tool_walkthrough`.
- **Resources** — `@`-mentions for reference docs:
  `@proto-bio:proto-tools://tools/<key>`, `@proto-bio:bio://constraints/<key>`, `…/schemas/<key>`, `…/citations/<key>`.

The authoritative, always-current surface is the `instructions` block in [`proto_client/mcp/server.py`](../proto_client/mcp/server.py).

## Working with output assets

When you call the Python SDK directly, large cloud outputs (structures, logits, PAE matrices, embeddings) come back as `AssetRef` objects rather than inline JSON. The `client.assets` namespace fetches their bytes on demand:

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

The client fetches only through authenticated Proto API origins, and strips authentication and end-user identity headers before following any redirect away from those origins. Not every ref is fetchable: upload-allocation refs, reference-database refs without an API-readable URL, and refs missing a `url` are rejected. Async clients expose the same namespace with `await`.

## How it works under the hood

Each agent tool call becomes an HTTP request to `https://mcp.evodesign.org/mcp` carrying your `Authorization: Bearer <key>` header. The server builds a **per-request client with your key**, calls the Proto tools/runs APIs, and returns validated results. There is no shared state between users, and your key never touches the server's environment.
