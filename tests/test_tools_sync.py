"""Streaming-log tests for the tools namespace; non-streaming tools tests live in ``test_tools.py``.

Iterator + cursor semantics are exercised against the shared NDJSON helpers in
``test_runs_sync.py``; tests here only verify URL/param wiring and that the
``get_job_logs`` wrapper packs records and terminator into a :class:`LogsPage`.
"""

from typing import Any

import httpx
from helpers import end_line, log_line, logs_payload, make_async_tools_ns, make_sync_tools_ns, ndjson_response

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


async def test_async_get_job_logs_packs_records_and_terminator():
    payload = logs_payload(log_line(10), end_line(reason="completed", final_seq=10))
    page = await make_async_tools_ns(lambda _: ndjson_response(payload)).get_job_logs("blast", "j1")
    assert [r.seq for r in page.records] == [10]
    assert (page.next_since, page.end_reason) == (None, "completed")
