"""Minimal command-line interface for submitting Proto Bio jobs.

A thin shell over :class:`~proto_client.ProtoClient`: submit tool jobs and
optimization runs, then write the result JSON and download any output assets.
Discovery, typed validation, and human-readable formatting are intentionally
left to proto-tools / the MCP server; this CLI deals in JSON and files.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from proto_client import AssetRef, ProtoClient
from proto_client.errors import ProtoAPIError
from proto_client.utils.asset_helpers import walk_assetrefs


def _read_json(path: str) -> Any:
    """Load JSON from *path*, or from stdin when *path* is ``-``."""
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(text)


def _emit_json(obj: Any, dest: str | None) -> None:
    """Write *obj* as indented JSON to stdout, or to *dest* when given."""
    text = json.dumps(obj, indent=2, default=str)
    if dest is None or dest == "-":
        print(text)
        return
    Path(dest).write_text(text + "\n")
    print(dest, file=sys.stderr)


def _download_assets(value: Any, client: ProtoClient, out_dir: Path, seen: dict[str, Path]) -> Any:
    """Recursively download AssetRefs in *value* to *out_dir*, rewriting each to its local path."""

    def _download(ref_value: Any) -> Any:
        ref = AssetRef.model_validate(ref_value)  # walk_assetrefs only yields refs
        if ref.id in seen:
            return str(seen[ref.id])
        dest = out_dir / ref.suggested_filename()
        if dest.exists():
            dest = out_dir / f"{Path(ref.id).name}_{dest.name}"
        client.assets.download(ref, dest)
        seen[ref.id] = dest
        return str(dest)

    return walk_assetrefs(value, _download)


# --- Commands (each takes an explicit client; returns an exit code) ---


def cmd_tools_run(client: ProtoClient, args: argparse.Namespace) -> int:
    """Submit a tool job, poll to completion, emit the result, download assets."""
    inputs = _read_json(args.inputs)
    config = _read_json(args.config) if args.config else None
    job = client.tools.run(args.key, inputs, config, timeout=float("inf"))
    result = job.result
    if args.assets is not None and result is not None:
        out_dir = Path(args.assets)
        out_dir.mkdir(parents=True, exist_ok=True)
        result = _download_assets(result, client, out_dir, {})
    _emit_json(result, args.output)
    return 0


def cmd_tools_example(client: ProtoClient, args: argparse.Namespace) -> int:
    """Emit a tool's minimal valid input dict (a scaffold for ``tools run``)."""
    _emit_json(client.tools.get_example(args.key).example_input, args.output)
    return 0


def cmd_runs_submit(client: ProtoClient, args: argparse.Namespace) -> int:
    """Submit an optimization run; with ``--wait`` poll to completion and optionally export."""
    if args.export and not args.wait:
        print("error: --export requires --wait", file=sys.stderr)
        return 2
    program = _read_json(args.program)
    if args.wait:
        run = client.runs.run(program, timeout=float("inf"))
        if args.export:
            print(client.runs.export(run.id, args.export))
        else:
            _emit_json(run.model_dump(mode="json"), None)
        return 0
    created = client.runs.create(program, execute=not args.no_execute)
    print(created.run_id)
    return 0


def cmd_runs_status(client: ProtoClient, args: argparse.Namespace) -> int:
    """Emit a run's current status and stage results."""
    _emit_json(client.runs.get(args.run_id).model_dump(mode="json"), args.output)
    return 0


def cmd_runs_export(client: ProtoClient, args: argparse.Namespace) -> int:
    """Download a run's results zip and print the on-disk path."""
    print(client.runs.export(args.run_id, args.path))
    return 0


def cmd_me(client: ProtoClient, _args: argparse.Namespace) -> int:
    """Print the calling key's workspace, tier, scopes, and credits."""
    me = client.me()
    print(f"workspace: {me.workspace_name} ({me.workspace_id})")
    print(f"tier:      {me.tier}")
    print(f"scopes:    {', '.join(me.scopes)}")
    if me.credit_cap is None:
        print("credits:   uncapped")
    else:
        print(f"credits:   {me.remaining_credits} / {me.credit_cap}")
    return 0


# --- Parser ---


def build_parser() -> argparse.ArgumentParser:
    """Build the ``proto-client`` argument parser."""
    parser = argparse.ArgumentParser(prog="proto-client", description="Proto Bio command-line client.")
    parser.add_argument("--api-key", help="API key (overrides PROTO_API_KEY).")
    sub = parser.add_subparsers(dest="group", required=True)

    # tools
    tools = sub.add_parser("tools", help="Run bioinformatics tools.").add_subparsers(dest="action", required=True)
    p_run = tools.add_parser("run", help="Submit a tool job and wait for the result.")
    p_run.add_argument("key", help="Tool key, e.g. esmfold-prediction.")
    p_run.add_argument("--inputs", required=True, metavar="FILE", help="JSON inputs file (or - for stdin).")
    p_run.add_argument("--config", metavar="FILE", help="Optional JSON config file.")
    p_run.add_argument("-o", "--output", metavar="FILE", help="Write result JSON here (default: stdout).")
    p_run.add_argument("--assets", metavar="DIR", help="Download output assets into this directory.")
    p_run.set_defaults(func=cmd_tools_run)
    p_ex = tools.add_parser("example", help="Print a tool's minimal valid input.")
    p_ex.add_argument("key", help="Tool key.")
    p_ex.add_argument("-o", "--output", metavar="FILE", help="Write the example here (default: stdout).")
    p_ex.set_defaults(func=cmd_tools_example)

    # runs
    runs = sub.add_parser("runs", help="Submit optimization runs.").add_subparsers(dest="action", required=True)
    p_submit = runs.add_parser("submit", help="Submit an optimization run.")
    p_submit.add_argument("program", metavar="FILE", help="Program JSON file (or - for stdin).")
    mode = p_submit.add_mutually_exclusive_group()
    mode.add_argument("--wait", action="store_true", help="Poll until the run reaches a terminal state.")
    mode.add_argument("--no-execute", action="store_true", help="Create the run idle (do not start stages).")
    p_submit.add_argument("--export", metavar="FILE", help="With --wait: write the results zip here.")
    p_submit.set_defaults(func=cmd_runs_submit)
    p_status = runs.add_parser("status", help="Show a run's status.")
    p_status.add_argument("run_id")
    p_status.add_argument("-o", "--output", metavar="FILE", help="Write status JSON here (default: stdout).")
    p_status.set_defaults(func=cmd_runs_status)
    p_export = runs.add_parser("export", help="Download a run's results zip.")
    p_export.add_argument("run_id")
    p_export.add_argument("path", nargs="?", help="Destination path (default: server filename in CWD).")
    p_export.set_defaults(func=cmd_runs_export)

    # me
    sub.add_parser("me", help="Show the calling key's workspace and credits.").set_defaults(func=cmd_me)

    # mcp
    p_mcp = sub.add_parser("mcp", help="Launch the MCP server for AI agents.")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio", help="Transport (default: stdio).")
    p_mcp.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1).")
    p_mcp.add_argument("--port", type=int, default=None, help="HTTP port (default: $PORT or 9300).")

    return parser


def _dispatch(argv: list[str]) -> int:
    """Parse *argv*, run the selected command, and return an exit code."""
    args = build_parser().parse_args(argv)

    if args.group == "mcp":
        try:
            from proto_client.mcp.__main__ import run_server
        except ImportError:
            print(
                "error: the MCP server needs the [mcp] extra; install with: pip install proto-client[mcp]",
                file=sys.stderr,
            )
            return 1
        try:
            run_server(args.transport, args.host, args.port)
        except KeyboardInterrupt:
            return 130
        return 0

    try:
        with ProtoClient(api_key=args.api_key) as client:
            code: int = args.func(client, args)
            return code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except (ProtoAPIError, RuntimeError, ValueError, OSError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    """Console-script entry point for ``proto-client``."""
    sys.exit(_dispatch(sys.argv[1:]))


if __name__ == "__main__":
    main()
