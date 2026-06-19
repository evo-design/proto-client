# Using the Proto Bio MCP server

Connect any MCP-compatible AI agent — Claude Code, Claude Desktop, Cursor, VS Code Copilot, Codex, Gemini — to Proto Bio, and drive bioinformatics tools and sequence-optimization runs through natural language. The hosted server needs **nothing installed**: you point your agent at a URL and authenticate with your Proto API key.

## Prerequisites

- A **Proto Bio API key** from your workspace.

The key is passed as a **Bearer token**. The hosted server holds no key of its own, so every request authenticates as *you*; your key never lives on the server.

## 1. Connect

### Hosted (recommended — no install)

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

Cursor, VS Code, Codex, and Gemini use the same URL with their own config shape — see the per-agent snippets in the [README](../README.md#hosted-http).

### Verify the connection

In a Claude Code session, run `/mcp`. You should see **proto-bio · Connected** with a tool count greater than zero. If it shows **0 tools** or **authentication failed**, your Bearer token is missing or wrong.



Prefer to run it yourself? Install the extra and launch over stdio, or build the Docker image — see [Local (stdio)](../README.md#local-stdio) in the README.

## 2. First call — confirm your key

Just talk to your agent; it picks the right tool. The cleanest first call confirms your key end to end:

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

## How it works under the hood

Each agent tool call becomes an HTTP request to `https://mcp.evodesign.org/mcp` carrying your `Authorization: Bearer <key>` header. The server builds a **per-request client with your key**, calls the Proto tools/runs APIs, and returns validated results. There is no shared state between users, and your key never touches the server's environment.
