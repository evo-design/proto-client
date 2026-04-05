"""Smoke tests for the unasync-generated sync ``RunsNamespace``.

The async test suite in ``test_runs_async.py`` exercises the logic; these
tests exist to verify that the token-level transform actually produced a
working sync module — catching unasync breakage the moment it happens.
"""

from __future__ import annotations

import httpx
import pytest

from proto_client.runs import RunsNamespace


def make_ns(handler) -> RunsNamespace:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.test")
    return RunsNamespace(http)


def test_sync_create_and_get():
    def handler(request):
        if request.method == "POST" and request.url.path == "/runs":
            return httpx.Response(
                200, json={"run_id": "x", "status": "running", "message": ""}
            )
        if request.method == "GET" and request.url.path == "/runs/x":
            return httpx.Response(200, json={"id": "x", "status": "running"})
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_ns(handler)
    created = ns.create({"constructs": [{}], "optimization_stages": [{}]})
    assert created["run_id"] == "x"
    assert ns.get("x")["status"] == "running"


def test_sync_cancel_propagates_400():
    def handler(_request):
        return httpx.Response(400, json={"detail": "Cannot cancel completed run"})

    ns = make_ns(handler)
    with pytest.raises(httpx.HTTPStatusError):
        ns.cancel("done")


def test_sync_validate():
    def handler(request):
        assert request.url.path == "/validate"
        return httpx.Response(200, json={"valid": True, "message": "ok"})

    assert (
        make_ns(handler).validate({"constructs": [], "optimization_stages": []})[
            "valid"
        ]
        is True
    )


def test_sync_timepoints_stage_filter():
    def handler(request):
        assert request.url.path == "/runs/abc/stages/0/timepoints"
        return httpx.Response(200, json=[])

    make_ns(handler).get_timepoints("abc", stage=0, timepoint=1)


def test_sync_discovery_endpoints():
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[])

    ns = make_ns(handler)
    ns.list_constraints()
    ns.list_generators()
    ns.list_optimizers()
    assert seen == ["/constraints", "/generators", "/optimizers"]


def test_sync_run_polls_until_completed(monkeypatch):
    # Replace the (generated) blocking sleep with a no-op.
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    counter = {"n": 0}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, json={"run_id": "r", "status": "pending", "message": ""}
            )
        counter["n"] += 1
        if counter["n"] < 2:
            return httpx.Response(200, json={"id": "r", "status": "running"})
        return httpx.Response(200, json={"id": "r", "status": "completed"})

    ns = make_ns(handler)
    final = ns.run(
        {"constructs": [{}], "optimization_stages": [{}]}, poll_interval=0.01
    )
    assert final["status"] == "completed"


def test_sync_run_short_circuits_on_instant_failure():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, json={"run_id": "r", "status": "failed", "message": ""}
            )
        return httpx.Response(
            200, json={"id": "r", "status": "failed", "error_message": "boom"}
        )

    ns = make_ns(handler)
    with pytest.raises(RuntimeError, match="boom"):
        ns.run({"constructs": [{}], "optimization_stages": [{}]})


def test_sync_run_short_circuits_on_instant_completed():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, json={"run_id": "r", "status": "completed", "message": ""}
            )
        return httpx.Response(
            200, json={"id": "r", "status": "completed", "stage_results": []}
        )

    assert (
        make_ns(handler).run({"constructs": [{}], "optimization_stages": [{}]})[
            "status"
        ]
        == "completed"
    )
