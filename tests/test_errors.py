"""Status-code → error class mapping and field extraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from proto_client.errors import (
    ProtoAPIError,
    ProtoAuthError,
    ProtoConflictError,
    ProtoNotFoundError,
    ProtoRateLimitError,
    ProtoServerError,
    ProtoValidationError,
    from_response,
    parse_retry_after,
)


def _response(
    status: int,
    json: dict | list | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=json,
        headers=headers or {},
        request=httpx.Request("GET", "https://proto-tools.evodesign.org/x"),
    )


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (401, ProtoAuthError),
        (403, ProtoAuthError),
        (404, ProtoNotFoundError),
        (409, ProtoConflictError),
        (422, ProtoValidationError),
        (429, ProtoRateLimitError),
        (500, ProtoServerError),
        (502, ProtoServerError),
        (503, ProtoServerError),
        (504, ProtoServerError),
    ],
)
def test_status_maps_to_class(status: int, cls: type[ProtoAPIError]) -> None:
    err = from_response(_response(status, {"detail": "boom"}))
    assert isinstance(err, cls)
    assert err.status_code == status
    assert err.message == "boom"


def test_unknown_4xx_falls_back_to_base() -> None:
    err = from_response(_response(418, {"detail": "teapot"}))
    assert type(err) is ProtoAPIError
    assert err.status_code == 418


def test_request_id_extracted_from_header() -> None:
    err = from_response(
        _response(500, {"detail": "oops"}, {"X-Request-ID": "req_abc123"})
    )
    assert err.request_id == "req_abc123"


def test_request_id_none_when_missing() -> None:
    err = from_response(_response(500, {"detail": "oops"}))
    assert err.request_id is None


def test_fastapi_validation_detail_extracted() -> None:
    body = {
        "detail": [
            {
                "loc": ["body", "sequences", 0],
                "msg": "string does not match regex",
                "type": "value_error.str.regex",
            },
            {
                "loc": ["body", "name"],
                "msg": "field required",
                "type": "value_error.missing",
            },
        ]
    }
    err = from_response(_response(422, body))
    assert isinstance(err, ProtoValidationError)
    assert len(err.errors) == 2
    assert err.errors[0]["loc"] == ["body", "sequences", 0]
    # Message falls back to the first detail's msg.
    assert err.message == "string does not match regex"


def test_string_detail_for_http_exception() -> None:
    err = from_response(_response(404, {"detail": "Unknown tool: 'foo'"}))
    assert err.message == "Unknown tool: 'foo'"


def test_non_json_body_uses_default_message() -> None:
    resp = httpx.Response(
        status_code=500,
        content=b"<html>internal error</html>",
        request=httpx.Request("GET", "https://proto-tools.evodesign.org/x"),
    )
    err = from_response(resp)
    assert err.status_code == 500
    assert err.message == "HTTP 500"


def test_retry_after_numeric() -> None:
    err = from_response(_response(429, {"detail": "slow down"}, {"Retry-After": "3.5"}))
    assert isinstance(err, ProtoRateLimitError)
    assert err.retry_after == 3.5


def test_retry_after_http_date() -> None:
    # ~5s in the future.
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    header = format_datetime(future, usegmt=True)
    err = from_response(_response(429, {"detail": "rl"}, {"Retry-After": header}))
    assert isinstance(err, ProtoRateLimitError)
    assert err.retry_after is not None
    # Allow slack for test execution time.
    assert 3.0 <= err.retry_after <= 6.0


def test_retry_after_http_date_in_past_clamps_to_zero() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=60)
    header = format_datetime(past, usegmt=True)
    assert parse_retry_after(header) == 0.0


def test_retry_after_missing_or_garbage() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("   ") is None
    assert parse_retry_after("not-a-date") is None


def test_error_str_includes_status_and_request_id() -> None:
    err = from_response(_response(500, {"detail": "boom"}, {"X-Request-ID": "req_1"}))
    s = str(err)
    assert "500" in s
    assert "boom" in s
    assert "req_1" in s


def test_error_str_without_request_id() -> None:
    err = from_response(_response(500, {"detail": "boom"}))
    assert "request_id" not in str(err)


def test_conflict_on_cancel_is_not_rate_limit() -> None:
    # Explicit regression per the issue comment: 409 on
    # POST /tools/{key}/jobs/{job_id}/cancel must be ProtoConflictError,
    # which the retry transport does not retry.
    err = from_response(_response(409, {"detail": "Job already completed"}))
    assert isinstance(err, ProtoConflictError)
    assert not isinstance(err, ProtoRateLimitError)
