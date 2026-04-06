"""Smoke tests for the unasync-generated sync ``RunsNamespace``.

The async test suite in ``test_runs_async.py`` exercises the logic; these
tests exist to verify that the token-level transform actually produced a
working sync module — catching unasync breakage the moment it happens.
"""

from __future__ import annotations

import httpx

from proto_client.runs import RunsNamespace


def make_ns(handler) -> RunsNamespace:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.test")
    return RunsNamespace(http)


def test_sync_create_and_get():
    def handler(request):
        if request.method == "POST" and request.url.path == "/runs":
            return httpx.Response(200, json={"run_id": "x", "status": "running", "message": ""})
        if request.method == "GET" and request.url.path == "/runs/x":
            return httpx.Response(200, json={"id": "x", "status": "running"})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_ns(handler)
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

    ns = make_ns(handler)
    final = ns.run({"constructs": [{}], "optimization_stages": [{}]}, poll_interval=0.01)
    assert final["status"] == "completed"
