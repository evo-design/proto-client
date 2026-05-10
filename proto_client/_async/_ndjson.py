"""Async NDJSON streaming helpers shared by runs.iter_logs and tools.iter_job_logs."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from proto_client.errors import from_response
from proto_client.models import LogRecord, LogsEnd, LogsPage

logger = logging.getLogger(__name__)


async def _aiter_ndjson_records(
    http: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
) -> AsyncIterator[LogRecord | LogsEnd]:
    """Stream NDJSON log items, yielding the :class:`LogsEnd` terminator (if any) then stopping."""
    logger.debug("GET %s (stream)", path)
    async with http.stream("GET", path, params=params) as resp:
        logger.debug("GET %s -> %d", path, resp.status_code)
        if resp.is_error:
            await resp.aread()
            raise from_response(resp)
        async for line in resp.aiter_lines():
            if not line:
                continue
            payload = json.loads(line)
            if payload["type"] == "end":
                yield LogsEnd.model_validate(payload)
                return
            yield LogRecord.model_validate(payload)


async def _acollect_logs_page(
    items: AsyncIterator[LogRecord | LogsEnd],
    since: int | None,
) -> LogsPage:
    """Drain *items* into a :class:`LogsPage`."""
    records: list[LogRecord] = []
    end_reason: Literal["completed", "truncated", "idle_timeout"] | None = None
    async for item in items:
        if isinstance(item, LogsEnd):
            end_reason = item.reason
        else:
            records.append(item)
    if end_reason is not None:
        next_since: int | None = None
    elif records:
        next_since = records[-1].seq
    else:
        next_since = since
    return LogsPage(records=records, next_since=next_since, end_reason=end_reason)
