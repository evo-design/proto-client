"""Tests for the sync ``RunsNamespace``.

Covers all methods and branches in ``proto_client/runs.py``, including
error paths, the ``run()`` polling convenience, and the ``_check_terminal``
helper.
"""

from typing import Any

import httpx
import pytest
from helpers import make_sync_ns, run_response_json

from proto_client.errors import ProtoAPIError, ProtoValidationError, RunCancelledError, RunFailedError
from proto_client.models import (
    CancelRunResponse,
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    OptimizerSpec,
    RunResponse,
    RunStatus,
    StageTimepointHistory,
    ValidationResponse,
)

# ── create() ──────────────────────────────────────────────────────────


def test_sync_create_and_get():
    def handler(request):
        if request.method == "POST" and request.url.path == "/api/v1/runs":
            return httpx.Response(200, json={"run_id": "x", "status": "running", "message": ""})
        if request.method == "GET" and request.url.path == "/api/v1/runs/x":
            return httpx.Response(200, json=run_response_json("x", "running"))
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_sync_ns(handler)
    created = ns.create({"constructs": [{}], "optimization_stages": [{}]})
    assert isinstance(created, CreateRunResponse)
    assert created.run_id == "x"
    got = ns.get("x")
    assert isinstance(got, RunResponse)
    assert got.status.value == "running"


def test_sync_create_with_webhook():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"run_id": "w1", "status": "running", "message": ""})

    ns = make_sync_ns(handler)
    ns.create(
        {"constructs": [{}]},
        webhook_url="https://hook.example/x",
        webhook_metadata={"user": "test"},
    )
    assert "webhook_url" in captured["body"]
    assert "webhook_metadata" in captured["body"]


def test_sync_create_without_webhook():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"run_id": "w2", "status": "pending", "message": ""})

    ns = make_sync_ns(handler)
    ns.create({"constructs": [{}]}, execute=False)
    assert "webhook_url" not in captured["body"]
    assert "webhook_metadata" not in captured["body"]


def test_sync_create_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "Internal error"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError) as exc_info:
        ns.create({"constructs": [{}]})
    assert exc_info.value.status_code == 500


# ── get() ─────────────────────────────────────────────────────────────


def test_sync_get_error():
    def handler(request):
        return httpx.Response(404, json={"detail": "Run not found"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError) as exc_info:
        ns.get("missing")
    assert exc_info.value.status_code == 404


# ── cancel() ──────────────────────────────────────────────────────────


def test_sync_cancel_ok():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/runs/r1/cancel"
        return httpx.Response(
            200,
            json={
                "message": "Run cancellation requested",
                "status": "cancelled",
                "details": {"already_cancelled": False, "task_terminated": True, "note": None},
            },
        )

    ns = make_sync_ns(handler)
    result = ns.cancel("r1")
    assert isinstance(result, CancelRunResponse)
    assert result.status == RunStatus.cancelled
    assert result.details.task_terminated is True
    assert result.details.already_cancelled is False


def test_sync_cancel_already_cancelled_returns_200():
    """Server returns 200 (not 400) for an already-cancelled run; details flags it."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": "Run was already cancelled",
                "status": "cancelled",
                "details": {"already_cancelled": True, "task_terminated": False, "note": "noop"},
            },
        )

    ns = make_sync_ns(handler)
    result = ns.cancel("done")
    assert result.details.already_cancelled is True


def test_sync_cancel_not_found():
    def handler(request):
        return httpx.Response(404, json={"detail": "Run not found"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError) as exc_info:
        ns.cancel("missing")
    assert exc_info.value.status_code == 404


# ── run_stage() ───────────────────────────────────────────────────────


def test_sync_run_stage_success():
    def handler(request):
        if request.method == "POST" and request.url.path == "/api/v1/runs/r1/stages/2/start":
            return httpx.Response(200, json=run_response_json("r1", "running", current_stage=2))
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    ns = make_sync_ns(handler)
    result = ns.run_stage("r1", 2)
    assert isinstance(result, RunResponse)
    assert result.current_stage == 2


def test_sync_run_stage_error():
    def handler(request):
        return httpx.Response(400, json={"detail": "Stage already running"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError) as exc_info:
        ns.run_stage("r1", 0)
    assert exc_info.value.status_code == 400


# ── validate() ────────────────────────────────────────────────────────


def test_sync_validate_ok():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/programs/validate"
        return httpx.Response(200, json={"valid": True, "message": "ok"})

    ns = make_sync_ns(handler)
    result = ns.validate({"constructs": [], "optimization_stages": []})
    assert isinstance(result, ValidationResponse)
    assert result.valid is True


def test_sync_validate_error():
    def handler(request):
        return httpx.Response(422, json={"detail": [{"msg": "Missing field", "loc": ["body"], "type": "missing"}]})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoValidationError) as exc_info:
        ns.validate({})
    assert exc_info.value.status_code == 422


# ── get_timepoints() ─────────────────────────────────────────────────


def test_sync_get_timepoints_all_stages():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 0, "timepoints": []}])

    ns = make_sync_ns(handler)
    result = ns.get_timepoints("abc", offset=5, limit=100)
    assert captured["path"] == "/api/v1/runs/abc/timepoints"
    assert captured["query"] == {"limit": "100", "offset": "5"}
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], StageTimepointHistory)


def test_sync_get_timepoints_single_stage_with_filter():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 1, "timepoints": []}])

    ns = make_sync_ns(handler)
    ns.get_timepoints("abc", stage=1, timepoint=5, limit=10)
    assert captured["path"] == "/api/v1/runs/abc/stages/1/timepoints"
    assert captured["query"] == {"limit": "10", "timepoint": "5"}


def test_sync_get_timepoints_rejects_filter_without_stage():
    ns = make_sync_ns(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match="timepoint filter"):
        ns.get_timepoints("abc", timepoint=5)


def test_sync_get_timepoints_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "DB error"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError):
        ns.get_timepoints("abc")


def test_sync_get_timepoints_stage_no_timepoint_filter():
    """Stage is set but timepoint is None — no timepoint param in query."""
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 0, "timepoints": []}])

    ns = make_sync_ns(handler)
    ns.get_timepoints("abc", stage=0)
    assert captured["path"] == "/api/v1/runs/abc/stages/0/timepoints"
    assert "timepoint" not in captured["query"]


# ── list_constraints / list_generators / list_optimizers ──────────────


_CONSTRAINT_JSON = {
    "key": "dummy",
    "label": "Dummy",
    "description": "A dummy constraint",
    "uses_gpu": False,
    "config_model": {},
    "tools_called": [],
    "category": None,
    "supported_sequence_types": ["protein"],
}

_GENERATOR_JSON = {
    "key": "dummy",
    "label": "Dummy",
    "description": "A dummy generator",
    "uses_gpu": False,
    "config_model": {},
    "category": "default",
    "tools_called": [],
    "supported_sequence_types": ["protein"],
}

_OPTIMIZER_JSON = {
    "key": "dummy",
    "label": "Dummy",
    "description": "A dummy optimizer",
    "uses_gpu": False,
    "config_model": {},
    "targets_single_segment": False,
}


def test_sync_list_constraints():
    def handler(request):
        assert request.url.path == "/api/v1/constraints"
        return httpx.Response(200, json=[_CONSTRAINT_JSON])

    ns = make_sync_ns(handler)
    result = ns.list_constraints()
    assert len(result) == 1
    assert isinstance(result[0], ConstraintSpec)
    assert result[0].key == "dummy"


def test_sync_list_constraints_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "boom"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError):
        ns.list_constraints()


def test_sync_list_generators():
    def handler(request):
        assert request.url.path == "/api/v1/generators"
        return httpx.Response(200, json=[_GENERATOR_JSON])

    ns = make_sync_ns(handler)
    result = ns.list_generators()
    assert len(result) == 1
    assert isinstance(result[0], GeneratorSpec)
    assert result[0].key == "dummy"


def test_sync_list_generators_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "boom"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError):
        ns.list_generators()


def test_sync_list_optimizers():
    def handler(request):
        assert request.url.path == "/api/v1/optimizers"
        return httpx.Response(200, json=[_OPTIMIZER_JSON])

    ns = make_sync_ns(handler)
    result = ns.list_optimizers()
    assert len(result) == 1
    assert isinstance(result[0], OptimizerSpec)
    assert result[0].key == "dummy"


def test_sync_list_optimizers_error():
    def handler(request):
        return httpx.Response(500, json={"detail": "boom"})

    ns = make_sync_ns(handler)
    with pytest.raises(ProtoAPIError):
        ns.list_optimizers()


# ── _check_terminal() ────────────────────────────────────────────────


def test_check_terminal_cancelled():
    from proto_client.runs import RunsNamespace

    resp = RunResponse.model_validate(run_response_json("r1", "cancelled"))
    with pytest.raises(RunCancelledError):
        RunsNamespace._check_terminal("r1", resp)


def test_check_terminal_unexpected_status():
    """A terminal status that isn't completed/cancelled/failed should raise AssertionError.

    This is a defensive assertion that should be unreachable in production --
    every real terminal status is handled by an explicit branch.  We test it
    to ensure the safety net fires if a new terminal status is ever added to
    the enum without a corresponding handler.
    """
    from proto_client.runs import RunsNamespace

    # Force a status that no branch handles.  'pending' is non-terminal in
    # practice, but _check_terminal only sees it if the caller already decided
    # the run is terminal, so it falls through to the assertion.
    resp = RunResponse.model_validate(run_response_json("r1", "pending"))
    with pytest.raises(AssertionError, match="Unexpected terminal status"):
        RunsNamespace._check_terminal("r1", resp)


def test_check_terminal_failed():
    from proto_client.runs import RunsNamespace

    resp = RunResponse.model_validate(run_response_json("r1", "failed", error_message="OOM"))
    with pytest.raises(RunFailedError) as exc_info:
        RunsNamespace._check_terminal("r1", resp)
    assert exc_info.value.run_id == "r1"
    assert exc_info.value.error_message == "OOM"


# ── run() convenience ────────────────────────────────────────────────


def test_sync_run_polls_until_completed(monkeypatch):
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    counter = {"n": 0}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r", "status": "pending", "message": ""})
        counter["n"] += 1
        if counter["n"] < 2:
            return httpx.Response(200, json=run_response_json("r", "running"))
        return httpx.Response(200, json=run_response_json("r", "completed"))

    ns = make_sync_ns(handler)
    final = ns.run({"constructs": [{}], "optimization_stages": [{}]}, poll_interval=0.01)
    assert isinstance(final, RunResponse)
    assert final.status.value == "completed"


def test_sync_run_short_circuits_on_cancelled(monkeypatch):
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r1", "status": "cancelled", "message": ""})
        return httpx.Response(200, json=run_response_json("r1", "cancelled"))

    ns = make_sync_ns(handler)
    with pytest.raises(RunCancelledError):
        ns.run({"constructs": [{}], "optimization_stages": [{}]})


def test_sync_run_times_out(monkeypatch):
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    times = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(runs_mod.time, "monotonic", lambda: next(times, 100.0))

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r1", "status": "running", "message": ""})
        return httpx.Response(200, json=run_response_json("r1", "running"))

    ns = make_sync_ns(handler)
    with pytest.raises(TimeoutError):
        ns.run({"constructs": [{}], "optimization_stages": [{}]}, timeout=1.0, poll_interval=0.01)


def test_sync_run_instant_terminal_disagreement_falls_through(monkeypatch):
    """When create() says terminal but get() says non-terminal, fall through to poll loop."""
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    get_calls = {"n": 0}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"run_id": "r1", "status": "completed", "message": ""})
        get_calls["n"] += 1
        if get_calls["n"] == 1:
            # First GET disagrees — says running (eventual consistency).
            return httpx.Response(200, json=run_response_json("r1", "running"))
        # Second GET returns completed.
        return httpx.Response(200, json=run_response_json("r1", "completed"))

    ns = make_sync_ns(handler)
    result = ns.run({"constructs": [{}], "optimization_stages": [{}]}, poll_interval=0.01)
    assert result.status.value == "completed"
    assert get_calls["n"] == 2


def test_sync_run_with_webhook_params(monkeypatch):
    import proto_client.runs as runs_mod

    monkeypatch.setattr(runs_mod, "_sleep", lambda _s: None)

    captured: dict[str, Any] = {}

    def handler(request):
        if request.method == "POST" and request.url.path == "/api/v1/runs":
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"run_id": "r1", "status": "pending", "message": ""})
        return httpx.Response(200, json=run_response_json("r1", "completed"))

    ns = make_sync_ns(handler)
    ns.run(
        {"constructs": [{}]},
        webhook_url="https://hook.example/x",
        webhook_metadata={"foo": "bar"},
        poll_interval=0.01,
    )
    assert "webhook_url" in captured["body"]
    assert "webhook_metadata" in captured["body"]
