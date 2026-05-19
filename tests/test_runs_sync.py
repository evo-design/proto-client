"""Tests for the sync ``RunsNamespace``.

Covers all methods and branches in ``proto_client/runs.py``, including
error paths, the ``run()`` polling convenience, and the ``_check_terminal``
helper.
"""

from typing import Any

import httpx
import pytest
from helpers import end_line, log_line, logs_payload, make_async_ns, make_sync_ns, ndjson_response, run_response_json

from proto_client.errors import ProtoAPIError, ProtoValidationError, RunCancelledError, RunFailedError
from proto_client.models import (
    CancelRunResponse,
    ConstraintSpec,
    CreateRunResponse,
    GeneratorSpec,
    LogRecord,
    LogsEnd,
    MetricPoint,
    OptimizerSpec,
    PaginatedTimepoints,
    RunResponse,
    RunStatus,
    RunTimepointResponse,
    StageMetrics,
    ValidationResponse,
)


def _timepoint_json(stage: int = 0, timepoint: int = 0) -> dict[str, Any]:
    return {
        "id": stage * 1000 + timepoint,
        "run_id": "abc",
        "optimizer_stage_idx": stage,
        "timepoint": timepoint,
        "best_result_idx": 0,
        "results": [],
        "created_at": "2026-04-05T12:00:00",
    }


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


def test_sync_export_saves_zip_with_stage_idx_and_maps_errors(tmp_path):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        if "missing" in request.url.path:
            return httpx.Response(404, json={"detail": "Run not found"})
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    ns = make_sync_ns(handler)
    out = ns.export("r1", tmp_path / "out.zip", stage_idx=2)
    assert captured["path"] == "/api/v1/runs/r1/export"
    assert captured["query"] == {"stage_idx": "2"}
    assert out == tmp_path / "out.zip"
    assert out.read_bytes() == b"PK\x03\x04zip-bytes"

    with pytest.raises(ProtoAPIError):
        ns.export("missing", tmp_path / "missing.zip")


def test_sync_export_creates_missing_parent_directories(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    out = make_sync_ns(handler).export("r1", tmp_path / "a" / "b" / "out.zip")
    assert out.read_bytes() == b"PK\x03\x04zip-bytes"


async def test_async_export_saves_zip_with_stage_idx_and_maps_errors(tmp_path):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        if "missing" in request.url.path:
            return httpx.Response(404, json={"detail": "Run not found"})
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    ns = make_async_ns(handler)
    out = await ns.export("r1", tmp_path / "out.zip", stage_idx=2)
    assert captured["path"] == "/api/v1/runs/r1/export"
    assert captured["query"] == {"stage_idx": "2"}
    assert out.read_bytes() == b"PK\x03\x04zip-bytes"

    with pytest.raises(ProtoAPIError):
        await ns.export("missing", tmp_path / "missing.zip")


async def test_async_export_creates_missing_parent_directories(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    out = await make_async_ns(handler).export("r1", tmp_path / "a" / "b" / "out.zip")
    assert out.read_bytes() == b"PK\x03\x04zip-bytes"


def test_sync_export_directory_path_appends_server_filename(tmp_path):
    """A directory path is treated as a destination dir, not the file itself."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-bytes",
            headers={"content-disposition": 'attachment; filename="auto.zip"'},
        )

    out = make_sync_ns(handler).export("r1", tmp_path)
    assert out == tmp_path / "auto.zip"


def test_sync_export_path_none_resolves_server_filename_else_convention_fallback(tmp_path, monkeypatch):
    """With path=None: use server's filename* (RFC 5987 non-ASCII case) or the convention fallback when absent."""
    monkeypatch.chdir(tmp_path)

    def with_disposition(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-bytes",
            headers={
                "content-disposition": (
                    'attachment; filename="Etude__2026-05-18_143005_stage-0.zip"; '
                    "filename*=UTF-8''%C3%89tude__2026-05-18_143005_stage-0.zip"
                ),
            },
        )

    out = make_sync_ns(with_disposition).export("r1")
    assert out == tmp_path / "Étude__2026-05-18_143005_stage-0.zip"

    def without_disposition(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    out = make_sync_ns(without_disposition).export("r1", project="My Project", stage_idx=2)
    assert out.parent == tmp_path
    assert out.name.startswith("My Project__")
    assert out.name.endswith("_stage-2.zip")


def test_sync_export_sanitizes_path_traversal_in_server_filename(tmp_path, monkeypatch):
    """A hostile server can't escape CWD via ../ in Content-Disposition."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-bytes",
            headers={"content-disposition": "attachment; filename*=UTF-8''..%2F..%2Fetc%2Fevil.zip"},
        )

    monkeypatch.chdir(tmp_path)
    out = make_sync_ns(handler).export("r1")
    assert out.resolve().is_relative_to(tmp_path.resolve())
    assert "/" not in out.name


async def test_async_export_directory_path_appends_server_filename(tmp_path):
    """Async mirror: directory path is treated as a destination dir."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-bytes",
            headers={"content-disposition": 'attachment; filename="auto.zip"'},
        )

    out = await make_async_ns(handler).export("r1", tmp_path)
    assert out == tmp_path / "auto.zip"


async def test_async_export_path_none_resolves_server_filename_else_convention_fallback(tmp_path, monkeypatch):
    """Async mirror: path=None uses server's filename or the convention fallback."""
    monkeypatch.chdir(tmp_path)

    def with_disposition(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-bytes",
            headers={"content-disposition": 'attachment; filename="proj__2026-05-18_143005_stage-0.zip"'},
        )

    out = await make_async_ns(with_disposition).export("r1")
    assert out == tmp_path / "proj__2026-05-18_143005_stage-0.zip"

    def without_disposition(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")

    out = await make_async_ns(without_disposition).export("r1", project="My Project", stage_idx=2)
    assert out.parent == tmp_path
    assert out.name.startswith("My Project__")
    assert out.name.endswith("_stage-2.zip")


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


# ── get_metrics() ────────────────────────────────────────────────────


def test_sync_get_metrics_all_stages():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json=[{"optimizer_stage_idx": 0, "points": []}])

    ns = make_sync_ns(handler)
    result = ns.get_metrics("abc")
    assert captured["path"] == "/api/v1/runs/abc/metrics"
    assert captured["query"] == {}
    assert len(result) == 1
    assert isinstance(result[0], StageMetrics)


def test_sync_get_metrics_with_filters():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "optimizer_stage_idx": 1,
                    "points": [{"timepoint": 0, "result_idx": 0, "energy_score": -2.5}],
                }
            ],
        )

    ns = make_sync_ns(handler)
    result = ns.get_metrics("abc", stage=1, resolution=200)
    assert captured["query"] == {"optimizer_stage_idx": "1", "resolution": "200"}
    assert result[0].points[0] == MetricPoint(timepoint=0, result_idx=0, energy_score=-2.5)


# ── get_timepoints() ─────────────────────────────────────────────────


def test_sync_get_timepoints_paginated():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"items": [_timepoint_json()], "total": 1, "page": 0, "page_size": 50},
        )

    ns = make_sync_ns(handler)
    result = ns.get_timepoints("abc", stage=0, page=2, page_size=25)
    assert captured["path"] == "/api/v1/runs/abc/timepoints"
    assert captured["query"] == {"optimizer_stage_idx": "0", "page": "2", "page_size": "25"}
    assert isinstance(result, PaginatedTimepoints)
    assert result.total == 1


def test_sync_get_timepoints_defaults():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "total": 0, "page": 0, "page_size": 50})

    make_sync_ns(handler).get_timepoints("abc")
    assert captured["query"] == {"page": "0", "page_size": "50"}


def test_sync_get_timepoints_error_propagates():
    """Representative error-mapping test — non-2xx → ProtoAPIError."""

    def handler(_):
        return httpx.Response(500, json={"detail": "DB error"})

    with pytest.raises(ProtoAPIError):
        make_sync_ns(handler).get_timepoints("abc")


# ── get_timepoint() ──────────────────────────────────────────────────


def test_sync_get_timepoint():
    captured: dict[str, Any] = {}

    def handler(request):
        captured["path"] = request.url.path
        return httpx.Response(200, json=_timepoint_json(stage=2, timepoint=7))

    result = make_sync_ns(handler).get_timepoint("abc", 2, 7)
    assert captured["path"] == "/api/v1/runs/abc/timepoints/2/7"
    assert isinstance(result, RunTimepointResponse)
    assert (result.optimizer_stage_idx, result.timepoint) == (2, 7)


# ── iter_timepoints() ────────────────────────────────────────────────


def test_sync_iter_timepoints_streams_ndjson():
    import json

    captured: dict[str, Any] = {}
    payload = b"\n".join(json.dumps(_timepoint_json(timepoint=i)).encode() for i in range(3))

    def handler(request):
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, content=payload, headers={"content-type": "application/x-ndjson"})

    rows = list(make_sync_ns(handler).iter_timepoints("abc", stage=1))
    assert captured["path"] == "/api/v1/runs/abc/timepoints/stream"
    assert captured["query"] == {"optimizer_stage_idx": "1"}
    assert [r.timepoint for r in rows] == [0, 1, 2]


def test_sync_iter_timepoints_error_before_body():
    """Stream errors must surface immediately, not silently yield zero rows."""

    def handler(_):
        return httpx.Response(404, json={"detail": "missing"})

    with pytest.raises(ProtoAPIError):
        list(make_sync_ns(handler).iter_timepoints("abc"))


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


# ── _iter_ndjson_records helper ──────────────────────────────────────


def test_iter_ndjson_yields_parsed_records():
    payload = logs_payload(
        log_line(1, "stdout", "a", level="info"),
        log_line(2, "stderr", "b", level="warning"),
    )
    rows = list(make_sync_ns(lambda _: ndjson_response(payload)).iter_logs("r1"))
    assert all(isinstance(r, LogRecord) for r in rows)
    assert [(r.seq, r.stream, r.level, r.msg) for r in rows] == [
        (1, "stdout", "info", "a"),
        (2, "stderr", "warning", "b"),
    ]


def test_iter_ndjson_skips_empty_lines():
    payload = b"\n\n" + log_line(1) + b"\n\n" + log_line(2) + b"\n\n"
    rows = list(make_sync_ns(lambda _: ndjson_response(payload)).iter_logs("r1"))
    assert [r.seq for r in rows] == [1, 2]


def test_iter_ndjson_terminates_on_end_marker():
    """Iterator yields the LogsEnd terminator then stops, even if more lines follow."""
    payload = logs_payload(
        log_line(1, "stdout", "first"),
        end_line(reason="completed", final_seq=1),
        log_line(2, "stdout", "should-not-see"),
    )
    rows = list(make_sync_ns(lambda _: ndjson_response(payload)).iter_logs("r1", follow=True))
    assert len(rows) == 2
    assert isinstance(rows[0], LogRecord)
    assert rows[0].msg == "first"
    assert isinstance(rows[1], LogsEnd)
    assert rows[1].reason == "completed"
    assert rows[1].final_seq == 1


def test_iter_ndjson_caller_break_releases_connection():
    payload = logs_payload(log_line(1), log_line(2), log_line(3))
    ns = make_sync_ns(lambda _: ndjson_response(payload))
    for rec in ns.iter_logs("r1"):
        if isinstance(rec, LogRecord) and rec.seq == 1:
            break
    seqs = [r.seq for r in ns.iter_logs("r2") if isinstance(r, LogRecord)]
    assert seqs == [1, 2, 3]


def test_iter_ndjson_error_before_body_raises():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    with pytest.raises(ProtoAPIError):
        list(make_sync_ns(handler).iter_logs("r1"))


# ── runs.iter_logs / runs.get_logs ───────────────────────────────────


def test_sync_iter_logs_path_and_params():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return ndjson_response(logs_payload(log_line(1)))

    rows = list(make_sync_ns(handler).iter_logs("r1", since=42, follow=True, limit=200))
    assert captured["path"] == "/api/v1/runs/r1/logs"
    assert captured["query"] == {"since": "42", "follow": "true", "limit": "200"}
    assert isinstance(rows[0], LogRecord) and rows[0].seq == 1


@pytest.mark.parametrize(
    ("payload", "since_in", "expected_seqs", "expected_next_since", "expected_end_reason"),
    [
        (logs_payload(log_line(10), log_line(11)), None, [10, 11], 11, None),
        (
            logs_payload(log_line(5), end_line(reason="completed", final_seq=5)),
            None,
            [5],
            None,
            "completed",
        ),
        (b"", 7, [], 7, None),
        (b"", None, [], None, None),
        (logs_payload(end_line(reason="completed", final_seq=3)), None, [], None, "completed"),
        (
            logs_payload(log_line(8), end_line(reason="truncated", final_seq=8)),
            None,
            [8],
            None,
            "truncated",
        ),
    ],
    ids=[
        "no-terminator-resumes-from-last-seq",
        "terminator-clears-cursor-and-sets-end-reason",
        "empty-page-preserves-cursor",
        "empty-page-no-cursor-stays-none",
        "terminator-only-clears-cursor",
        "truncated-terminator-surfaces-as-end-reason",
    ],
)
def test_sync_get_logs_next_since(
    payload: bytes,
    since_in: int | None,
    expected_seqs: list[int],
    expected_next_since: int | None,
    expected_end_reason: str | None,
):
    page = make_sync_ns(lambda _: ndjson_response(payload)).get_logs("r1", since=since_in)
    assert [r.seq for r in page.records] == expected_seqs
    assert page.next_since == expected_next_since
    assert page.end_reason == expected_end_reason


async def test_async_iter_logs_path_and_params():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return ndjson_response(logs_payload(log_line(1)))

    rows = [r async for r in make_async_ns(handler).iter_logs("r1", since=42, follow=True, limit=200)]
    assert captured["path"] == "/api/v1/runs/r1/logs"
    assert captured["query"] == {"since": "42", "follow": "true", "limit": "200"}
    assert isinstance(rows[0], LogRecord) and rows[0].seq == 1


def test_sync_iter_logs_passes_tail_param():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = dict(request.url.params)
        return ndjson_response(logs_payload(log_line(1)))

    list(make_sync_ns(handler).iter_logs("r1", tail=600))
    assert captured["query"].get("tail") == "600"
    assert "since" not in captured["query"]


def test_sync_get_logs_with_tail_forces_next_since_none():
    """Even without a terminator (e.g. partial response), tail mode must not set a resume cursor."""
    payload_no_terminator = logs_payload(log_line(10), log_line(11))
    page = make_sync_ns(lambda _: ndjson_response(payload_no_terminator)).get_logs("r1", tail=10)
    assert [r.seq for r in page.records] == [10, 11]
    assert page.next_since is None
    assert page.end_reason is None


# ── runs.iter_logs / runs.get_logs — level + stream filters ───────────


@pytest.mark.parametrize(
    ("kwargs", "expected_levels", "expected_streams"),
    [
        ({"level": ["warning", "error"]}, ["warning", "error"], []),
        ({"stream": ["stdout", "stderr"]}, [], ["stdout", "stderr"]),
        (
            {"since": 42, "follow": True, "limit": 200, "level": ["warning", "error"], "stream": ["stderr"]},
            ["warning", "error"],
            ["stderr"],
        ),
        ({}, [], []),
    ],
    ids=["level-only", "stream-only", "combined-with-passthrough", "omits-when-unset"],
)
def test_sync_iter_logs_filter_round_trip(
    kwargs: dict[str, Any], expected_levels: list[str], expected_streams: list[str]
):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["items"] = request.url.params.multi_items()
        return ndjson_response(logs_payload(log_line(1)))

    list(make_sync_ns(handler).iter_logs("r1", **kwargs))
    items = captured["items"]
    assert [v for k, v in items if k == "level"] == expected_levels
    assert [v for k, v in items if k == "stream"] == expected_streams
    if "since" in kwargs:
        assert ("since", str(kwargs["since"])) in items
    if "follow" in kwargs:
        assert ("follow", str(kwargs["follow"]).lower()) in items
    if "limit" in kwargs:
        assert ("limit", str(kwargs["limit"])) in items
