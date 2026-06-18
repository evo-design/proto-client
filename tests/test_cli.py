"""Tests for the proto-client CLI."""

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from helpers import job_payload, make_sync_ns, make_sync_tools_ns, run_response_json

from proto_client import cli
from proto_client.assets import AssetsNamespace
from proto_client.cli import (
    _dispatch,
    _download_assets,
    build_parser,
    cmd_runs_submit,
    cmd_tools_example,
    cmd_tools_run,
)
from proto_client.errors import ProtoAPIError
from proto_client.models import ToolExample


def test_tools_run_emits_result(tmp_path, capsys):
    infile = tmp_path / "in.json"
    infile.write_text(json.dumps({"sequences": ["MK"]}))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "j1", "status": "pending"})
        return httpx.Response(200, json=job_payload("completed", result={"score": 1.0}, completed=True))

    client = MagicMock()
    client.tools = make_sync_tools_ns(handler)
    args = build_parser().parse_args(["tools", "run", "esmfold-prediction", "--inputs", str(infile)])

    assert cmd_tools_run(client, args) == 0
    assert json.loads(capsys.readouterr().out) == {"score": 1.0}


def test_tools_example_to_stdout_and_file(tmp_path, capsys):
    client = MagicMock()
    client.tools.get_example.return_value = ToolExample(example_input={"sequences": ["MK"]})

    assert cmd_tools_example(client, argparse.Namespace(key="esmfold-prediction", output=None)) == 0
    assert json.loads(capsys.readouterr().out) == {"sequences": ["MK"]}

    out = tmp_path / "ex.json"
    cmd_tools_example(client, argparse.Namespace(key="esmfold-prediction", output=str(out)))
    assert json.loads(out.read_text()) == {"sequences": ["MK"]}


def test_download_assets_walk(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PDBDATA")

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test")
    client = MagicMock()
    client.assets = AssetsNamespace([http])
    ref = {"id": "a1", "kind": "output", "mime_type": "text/plain", "filename": "out.txt", "url": "https://api.test/a1"}

    result = _download_assets({"structure": ref, "score": 1.0}, client, tmp_path, {})

    assert result["score"] == 1.0
    assert result["structure"] == str(tmp_path / "out.txt")
    assert (tmp_path / "out.txt").read_bytes() == b"PDBDATA"


def test_download_assets_disambiguates_colliding_filenames(tmp_path):
    """Two distinct assets that share a filename must not clobber each other."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=request.url.path.encode())  # distinct bytes per asset id

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.test")
    client = MagicMock()
    client.assets = AssetsNamespace([http])
    ref1 = {"id": "a1", "kind": "output", "filename": "structure.pdb", "url": "https://api.test/a1"}
    ref2 = {"id": "a2", "kind": "output", "filename": "structure.pdb", "url": "https://api.test/a2"}

    result = _download_assets({"x": ref1, "y": ref2}, client, tmp_path, {})

    assert result["x"] != result["y"]
    assert Path(result["x"]).read_bytes() == b"/a1"
    assert Path(result["y"]).read_bytes() == b"/a2"


def test_runs_submit_prints_run_id(tmp_path, capsys):
    prog = tmp_path / "program.json"
    prog.write_text("{}")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"run_id": "r1", "status": "pending", "message": "ok"})

    client = MagicMock()
    client.runs = make_sync_ns(handler)
    args = build_parser().parse_args(["runs", "submit", str(prog)])

    assert cmd_runs_submit(client, args) == 0
    assert capsys.readouterr().out.strip() == "r1"


def test_runs_submit_wait_and_export(tmp_path, capsys):
    prog = tmp_path / "program.json"
    prog.write_text("{}")
    out_zip = tmp_path / "out.zip"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/runs"):
            return httpx.Response(202, json={"run_id": "r1", "status": "pending", "message": "ok"})
        if path.endswith("/export"):
            return httpx.Response(200, content=b"ZIPDATA")
        return httpx.Response(200, json=run_response_json("r1", "completed"))

    client = MagicMock()
    client.runs = make_sync_ns(handler)
    args = build_parser().parse_args(["runs", "submit", str(prog), "--wait", "--export", str(out_zip)])

    assert cmd_runs_submit(client, args) == 0
    assert out_zip.read_bytes() == b"ZIPDATA"
    assert capsys.readouterr().out.strip() == str(out_zip)


def test_runs_submit_wait_writes_run_json_to_output(tmp_path, capsys):
    prog = tmp_path / "program.json"
    prog.write_text("{}")
    out = tmp_path / "run.json"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"run_id": "r1", "status": "pending", "message": "ok"})
        return httpx.Response(200, json=run_response_json("r1", "completed"))

    client = MagicMock()
    client.runs = make_sync_ns(handler)
    args = build_parser().parse_args(["runs", "submit", str(prog), "--wait", "-o", str(out)])

    assert cmd_runs_submit(client, args) == 0
    assert json.loads(out.read_text())["id"] == "r1"


def test_runs_submit_export_requires_wait(tmp_path, capsys):
    prog = tmp_path / "program.json"
    prog.write_text("{}")
    args = build_parser().parse_args(["runs", "submit", str(prog), "--export", str(tmp_path / "o.zip")])

    assert cmd_runs_submit(MagicMock(), args) == 2
    assert "requires --wait" in capsys.readouterr().err


def test_dispatch_maps_api_error_to_exit_1(tmp_path, capsys, monkeypatch):
    infile = tmp_path / "in.json"
    infile.write_text("{}")
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.tools.run.side_effect = ProtoAPIError("boom", status_code=500)
    monkeypatch.setattr(cli, "ProtoClient", lambda **kwargs: fake)

    assert _dispatch(["tools", "run", "k", "--inputs", str(infile)]) == 1
    assert "error:" in capsys.readouterr().err


def test_dispatch_mcp_does_not_build_a_client(monkeypatch):
    pytest.importorskip("fastmcp")  # `mcp` subcommand imports the mcp package, which needs fastmcp
    seen = {}
    monkeypatch.setattr(
        "proto_client.mcp.__main__.run_server", lambda t, h, p: seen.update(transport=t, host=h, port=p)
    )
    monkeypatch.setattr(cli, "ProtoClient", MagicMock(side_effect=AssertionError("mcp must not build a client")))

    assert _dispatch(["mcp", "--transport", "stdio"]) == 0
    assert seen["transport"] == "stdio"
