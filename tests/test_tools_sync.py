"""Streaming-log tests for the tools namespace; non-streaming tools tests live in ``test_tools.py``.

Cursor / ``next_since`` semantics are covered in ``test_runs_sync.py`` (the same ``_ndjson``
helpers back both namespaces); tests here verify URL/param wiring and the level/stream filter
round-trip across the hand-written sync and async tools paths.
"""

from typing import Any

import httpx
import pytest
from helpers import log_line, logs_payload, make_async_tools_ns, make_sync_tools_ns, ndjson_response

from proto_client.models import LogRecord


def test_sync_iter_job_logs_path_and_params():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return ndjson_response(logs_payload(log_line(1)))

    rows = list(make_sync_tools_ns(handler).iter_job_logs("esmfold", "j1", since=42, follow=True, limit=200))
    assert captured["path"] == "/api/v1/tools/esmfold/jobs/j1/logs"
    assert captured["query"] == {"since": "42", "follow": "true", "limit": "200"}
    assert isinstance(rows[0], LogRecord) and rows[0].seq == 1


async def test_async_iter_job_logs_path_and_params():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params)
        return ndjson_response(logs_payload(log_line(1)))

    rows = [
        r async for r in make_async_tools_ns(handler).iter_job_logs("esmfold", "j1", since=42, follow=True, limit=200)
    ]
    assert captured["path"] == "/api/v1/tools/esmfold/jobs/j1/logs"
    assert captured["query"] == {"since": "42", "follow": "true", "limit": "200"}
    assert isinstance(rows[0], LogRecord) and rows[0].seq == 1


def test_logrecord_update_status_defaults_false_and_parses_true():
    """``update_status`` is omitted on the wire when false (defaults False) and parses True for phase markers."""
    base = {
        "type": "record",
        "seq": 1,
        "ts": "2026-05-09T12:34:56.789Z",
        "stream": "stdout",
        "level": "info",
        "msg": "x",
    }
    assert LogRecord.model_validate(base).update_status is False
    assert LogRecord.model_validate({**base, "seq": 2, "stream": "system", "update_status": True}).update_status is True


# ── iter_job_logs / get_job_logs — level + stream filters ─────────────


_FILTER_CASES = [
    ({"level": ["warning", "error"]}, ["warning", "error"], []),
    ({"stream": ["stdout", "stderr"]}, [], ["stdout", "stderr"]),
    (
        {"since": 42, "follow": True, "limit": 200, "level": ["warning", "error"], "stream": ["stderr"]},
        ["warning", "error"],
        ["stderr"],
    ),
    ({}, [], []),
]
_FILTER_IDS = ["level-only", "stream-only", "combined-with-passthrough", "omits-when-unset"]


def _capturing_handler(captured: dict[str, Any]):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["items"] = request.url.params.multi_items()
        return ndjson_response(logs_payload(log_line(1)))

    return handler


def _assert_filter_items(items, kwargs, expected_levels, expected_streams):
    assert [v for k, v in items if k == "level"] == expected_levels
    assert [v for k, v in items if k == "stream"] == expected_streams
    for key in ("since", "limit"):
        if key in kwargs:
            assert (key, str(kwargs[key])) in items
    if "follow" in kwargs:
        assert ("follow", str(kwargs["follow"]).lower()) in items


@pytest.mark.parametrize(("kwargs", "expected_levels", "expected_streams"), _FILTER_CASES, ids=_FILTER_IDS)
def test_sync_iter_job_logs_filter_round_trip(kwargs, expected_levels, expected_streams):
    captured: dict[str, Any] = {}
    list(make_sync_tools_ns(_capturing_handler(captured)).iter_job_logs("esmfold", "j1", **kwargs))
    _assert_filter_items(captured["items"], kwargs, expected_levels, expected_streams)


@pytest.mark.parametrize(("kwargs", "expected_levels", "expected_streams"), _FILTER_CASES, ids=_FILTER_IDS)
async def test_async_iter_job_logs_filter_round_trip(kwargs, expected_levels, expected_streams):
    """Hand-written async tools path — verify the filter round-trip matches sync."""
    captured: dict[str, Any] = {}
    ns = make_async_tools_ns(_capturing_handler(captured))
    [r async for r in ns.iter_job_logs("esmfold", "j1", **kwargs)]
    _assert_filter_items(captured["items"], kwargs, expected_levels, expected_streams)
