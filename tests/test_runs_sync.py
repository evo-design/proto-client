"""Smoke tests for the unasync-generated sync ``RunsNamespace``.

The async test suite in ``test_runs_async.py`` exercises the logic; these
tests exist to verify that the token-level transform actually produced a
working sync module — catching unasync breakage the moment it happens.
"""

import httpx
import pytest
from helpers import make_sync_ns

from proto_client.errors import RunFailedError


def test_sync_create_and_get():
    def handler(request):
        if request.method == "POST" and request.url.path == "/runs":
            return httpx.Response(200, json={"run_id": "x", "status": "running", "message": ""})
        if request.method == "GET" and request.url.path == "/runs/x":
            return httpx.Response(200, json={"id": "x", "status": "running"})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_sync_ns(handler)
    created = ns.create({"constructs": [{}], "optimization_stages": [{}]})
    assert created["run_id"] == "x"
    assert ns.get("x")["status"] == "running"


def test_sync_run_polls_until_completed(monkeypatch):
    # Replace the (generated) blocking sleep with a no-op.
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    counter = {"n": 0}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r", "status": "pending", "message": ""})
        counter["n"] += 1
        if counter["n"] < 2:
            return httpx.Response(200, json={"id": "r", "status": "running"})
        return httpx.Response(200, json={"id": "r", "status": "completed"})

    ns = make_sync_ns(handler)
    final = ns.run({"constructs": [{}], "optimization_stages": [{}]}, poll_interval=0.01)
    assert final["status"] == "completed"


def test_sync_run_short_circuits_on_failed(monkeypatch):
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r1", "status": "failed", "message": ""})
        # GET for the terminal status check
        return httpx.Response(
            200,
            json={"id": "r1", "status": "failed", "error_message": "OOM killed", "stage_results": []},
        )

    ns = make_sync_ns(handler)
    with pytest.raises(RunFailedError):
        ns.run({"constructs": [{}], "optimization_stages": [{}]})


def test_sync_cancel():
    def handler(request):
        if request.method == "DELETE" and request.url.path == "/runs/abc":
            return httpx.Response(200, json={"message": "cancelled", "status": "cancelled"})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_sync_ns(handler)
    result = ns.cancel("abc")
    assert result["status"] == "cancelled"
