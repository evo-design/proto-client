"""Retry transport behavior (sync)."""

import random
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from proto_client.utils.http import (
    RetryConfig,
    RetryTransport,
    compute_backoff,
)

_URL = "https://proto-tools.evodesign.org/x"
_REQ = httpx.Request("GET", _URL)


def _resp(status: int, **kwargs: Any) -> httpx.Response:
    return httpx.Response(status, request=_REQ, **kwargs)


def _sequence_handler(
    responses: list[httpx.Response | Exception],
) -> tuple[Callable[[httpx.Request], httpx.Response], SimpleNamespace]:
    counter = SimpleNamespace(n=0)

    def handler(request: httpx.Request) -> httpx.Response:
        assert counter.n < len(responses), f"MockTransport exhausted at call #{counter.n + 1}"
        item = responses[counter.n]
        counter.n += 1
        if isinstance(item, Exception):
            raise item
        return item

    return handler, counter


def _capturing_sleep() -> tuple[list[float], Callable[[float], None]]:
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


def _sync_transport(
    responses: list[httpx.Response | Exception],
    *,
    max_retries: int = 2,
    initial_delay: float = 0.5,
    jitter: float = 0.0,
    **cfg_kwargs: Any,
) -> tuple[RetryTransport, SimpleNamespace, list[float]]:
    handler, counter = _sequence_handler(responses)
    delays, sleep = _capturing_sleep()
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        jitter=jitter,
        **cfg_kwargs,
    )
    transport = RetryTransport(httpx.MockTransport(handler), config, sleep=sleep)
    return transport, counter, delays


def _get(transport: RetryTransport) -> httpx.Response:
    with httpx.Client(transport=transport) as client:
        return client.get(_URL)


def _post(transport: RetryTransport, *, headers: dict[str, str] | None = None) -> httpx.Response:
    with httpx.Client(transport=transport) as client:
        return client.post(_URL, headers=headers)


# ----------------------------------------------------------------------- config


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_retries": -1}, "max_retries must be >= 0"),
        ({"initial_delay": -0.1}, "initial_delay must be >= 0"),
        (
            {"initial_delay": 5.0, "max_delay": 1.0},
            "max_delay must be >= initial_delay",
        ),
        ({"factor": 0.5}, "factor must be >= 1.0"),
        ({"jitter": -0.1}, "jitter must be in"),
        ({"jitter": 1.5}, "jitter must be in"),
        ({"retry_after_max": -1.0}, "retry_after_max must be >= 0"),
    ],
)
def test_retry_config_rejects_invalid_values(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        RetryConfig(**kwargs)


# ----------------------------------------------------------------------- sync


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retries_on_retriable_status(status: int) -> None:
    transport, counter, _ = _sync_transport([_resp(status), _resp(200)], initial_delay=0.01)
    assert _get(transport).status_code == 200
    assert counter.n == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_does_not_retry_on_non_retriable_status(status: int) -> None:
    transport, counter, delays = _sync_transport(
        [_resp(status, json={"detail": "nope"}), _resp(200)],
        max_retries=3,
        initial_delay=0.01,
    )
    assert _get(transport).status_code == status
    assert counter.n == 1
    assert delays == []


def test_retries_on_connect_error_then_succeeds() -> None:
    transport, counter, _ = _sync_transport([httpx.ConnectError("refused"), _resp(200)], initial_delay=0.01)
    assert _get(transport).status_code == 200
    assert counter.n == 2


def test_does_not_retry_on_non_retriable_exception() -> None:
    transport, counter, delays = _sync_transport([httpx.InvalidURL("bad url")])
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.InvalidURL):
            client.get(_URL)
    assert counter.n == 1
    assert delays == []


def test_max_retries_cap_returns_final_error_response() -> None:
    transport, counter, delays = _sync_transport([_resp(503)] * 10, initial_delay=0.01)
    assert _get(transport).status_code == 503
    assert counter.n == 3  # 1 initial + 2 retries
    assert len(delays) == 2


def test_max_retries_cap_reraises_final_exception() -> None:
    transport, counter, delays = _sync_transport([httpx.ConnectError("down")] * 10, initial_delay=0.01)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            client.get(_URL)
    assert counter.n == 3
    assert len(delays) == 2


@pytest.mark.parametrize("status", [429, 503])
def test_retry_after_header_overrides_backoff(status: int) -> None:
    transport, _, delays = _sync_transport(
        [_resp(status, headers={"Retry-After": "7"}), _resp(200)],
    )
    assert _get(transport).status_code == 200
    assert delays == [7.0]


def test_exponential_backoff_across_attempts() -> None:
    transport, _, delays = _sync_transport(
        [_resp(500), _resp(500), _resp(500), _resp(200)],
        max_retries=3,
        factor=2.0,
        max_delay=30.0,
    )
    _get(transport)
    assert delays == [0.5, 1.0, 2.0]


def test_max_delay_cap() -> None:
    transport, _, delays = _sync_transport(
        [_resp(500)] * 10,
        max_retries=5,
        initial_delay=10.0,
        factor=10.0,
        max_delay=15.0,
    )
    _get(transport)
    assert all(d <= 15.0 for d in delays)
    assert delays[-1] == 15.0


def test_jitter_applied_within_expected_window() -> None:
    cfg = RetryConfig(max_retries=0, initial_delay=1.0, factor=2.0, jitter=0.1)
    rng = random.Random(12345)  # noqa: S311
    samples = [compute_backoff(0, cfg, rng=rng) for _ in range(200)]
    assert all(0.9 <= s <= 1.1 for s in samples)
    assert len(set(samples)) > 1


def test_mixed_exception_then_retriable_status_then_success() -> None:
    transport, counter, delays = _sync_transport(
        [httpx.ConnectError("refused"), _resp(503), _resp(200)],
        max_retries=3,
    )
    assert _get(transport).status_code == 200
    assert counter.n == 3
    assert delays == [0.5, 1.0]


def test_retries_on_remote_protocol_error_then_succeeds() -> None:
    transport, counter, _ = _sync_transport(
        [httpx.RemoteProtocolError("Server disconnected without sending a response."), _resp(200)],
        initial_delay=0.01,
    )
    assert _get(transport).status_code == 200
    assert counter.n == 2


def test_retry_after_capped_at_retry_after_max() -> None:
    # A hostile/buggy `Retry-After: 999999` must not park the client for days.
    transport, _, delays = _sync_transport(
        [_resp(429, headers={"Retry-After": "999999"}), _resp(200)],
        retry_after_max=120.0,
    )
    assert _get(transport).status_code == 200
    assert delays == [120.0]


# ------------------------------------------------------- idempotency-gated POST retries


def test_post_without_idempotency_key_not_retried_on_5xx() -> None:
    # Non-idempotent POST: surface the first 5xx rather than risk a duplicate side effect.
    transport, counter, delays = _sync_transport([_resp(503), _resp(200)], initial_delay=0.01)
    assert _post(transport).status_code == 503
    assert counter.n == 1
    assert delays == []


def test_post_without_idempotency_key_not_retried_on_network_error() -> None:
    transport, counter, delays = _sync_transport([httpx.ConnectError("down"), _resp(200)], initial_delay=0.01)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            client.post(_URL)
    assert counter.n == 1
    assert delays == []


def test_post_with_idempotency_key_is_retried() -> None:
    # An Idempotency-Key opts the POST into safe retries (the backend dedupes on it).
    transport, counter, _ = _sync_transport([_resp(503), _resp(200)], initial_delay=0.01)
    assert _post(transport, headers={"Idempotency-Key": "k1"}).status_code == 200
    assert counter.n == 2
