"""Retry transport behavior (sync + async)."""

from __future__ import annotations

import random
from types import SimpleNamespace

import httpx
import pytest

from proto_client._http import (
    AsyncRetryTransport,
    RetryConfig,
    RetryTransport,
    compute_backoff,
)


def _sequence_handler(
    responses: list[httpx.Response | Exception],
) -> tuple[callable, SimpleNamespace]:
    """Return a MockTransport handler that yields the next response per call."""
    counter = SimpleNamespace(n=0)

    def handler(request: httpx.Request) -> httpx.Response:
        item = responses[counter.n]
        counter.n += 1
        if isinstance(item, Exception):
            raise item
        return item

    return handler, counter


def _capturing_sleep() -> tuple[list[float], callable]:
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


def _capturing_async_sleep() -> tuple[list[float], callable]:
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


# --------------------------------------------------------------------------- sync


def test_retries_on_500_then_succeeds() -> None:
    handler, counter = _sequence_handler(
        [
            httpx.Response(500, json={"detail": "boom"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.5, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")

    assert resp.status_code == 200
    assert counter.n == 2
    assert delays == [0.5]


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retries_on_retriable_status(status: int) -> None:
    handler, counter = _sequence_handler(
        [
            httpx.Response(status, json={"detail": "x"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 200
    assert counter.n == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_does_not_retry_on_non_retriable_status(status: int) -> None:
    handler, counter = _sequence_handler(
        [
            httpx.Response(status, json={"detail": "nope"}),
            httpx.Response(200, json={"ok": True}),  # should never be reached
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=3, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")

    assert resp.status_code == status
    assert counter.n == 1
    assert delays == []


def test_retries_on_connect_error_then_succeeds() -> None:
    handler, counter = _sequence_handler(
        [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 200
    assert counter.n == 2


def test_does_not_retry_on_non_retriable_exception() -> None:
    handler, counter = _sequence_handler(
        [
            httpx.InvalidURL("bad url"),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.InvalidURL):
            client.get("https://proto-tools.evodesign.org/x")
    assert counter.n == 1
    assert delays == []


def test_max_retries_cap_returns_final_error_response() -> None:
    handler, counter = _sequence_handler(
        [httpx.Response(503, json={"detail": "down"})] * 10
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")

    # max_retries=2 → 1 initial + 2 retries = 3 calls, 2 sleeps.
    assert resp.status_code == 503
    assert counter.n == 3
    assert len(delays) == 2


def test_max_retries_cap_reraises_final_exception() -> None:
    handler, counter = _sequence_handler([httpx.ConnectError("down")] * 10)
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            client.get("https://proto-tools.evodesign.org/x")
    assert counter.n == 3
    assert len(delays) == 2


def test_retry_after_header_overrides_backoff() -> None:
    handler, _ = _sequence_handler(
        [
            httpx.Response(429, json={"detail": "rl"}, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.5, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        resp = client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 200
    assert delays == [7.0]


def test_429_without_retry_after_uses_computed_backoff() -> None:
    handler, _ = _sequence_handler(
        [
            httpx.Response(429, json={"detail": "rl"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.5, jitter=0.0),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://proto-tools.evodesign.org/x")
    assert delays == [0.5]


def test_exponential_backoff_across_attempts() -> None:
    handler, _ = _sequence_handler(
        [
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200),
        ]
    )
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(
            max_retries=3,
            initial_delay=0.5,
            factor=2.0,
            max_delay=30.0,
            jitter=0.0,
        ),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://proto-tools.evodesign.org/x")
    assert delays == [0.5, 1.0, 2.0]


def test_max_delay_cap() -> None:
    handler, _ = _sequence_handler([httpx.Response(500)] * 10)
    delays, sleep = _capturing_sleep()
    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(
            max_retries=5,
            initial_delay=10.0,
            factor=10.0,
            max_delay=15.0,
            jitter=0.0,
        ),
        sleep=sleep,
    )
    with httpx.Client(transport=transport) as client:
        client.get("https://proto-tools.evodesign.org/x")
    # All delays clamp at max_delay=15 once the geometric series blows past it.
    assert all(d <= 15.0 for d in delays)
    assert delays[-1] == 15.0


def test_jitter_applied_within_expected_window() -> None:
    cfg = RetryConfig(max_retries=0, initial_delay=1.0, factor=2.0, jitter=0.1)
    rng = random.Random(12345)
    samples = [compute_backoff(0, cfg, rng=rng) for _ in range(200)]
    # attempt=0 → base = 1.0, jitter ±0.1 → all samples in [0.9, 1.1].
    assert all(0.9 <= s <= 1.1 for s in samples)
    # And we're actually varying, not returning a constant.
    assert len(set(samples)) > 1


def test_arbitrary_request_headers_pass_through() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    transport = RetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=0),
    )
    with httpx.Client(transport=transport) as client:
        client.get(
            "https://proto-tools.evodesign.org/x",
            headers={"x-app-user-id": "user_42", "X-API-Key": "sk_test"},
        )
    assert seen_headers.get("x-app-user-id") == "user_42"
    assert seen_headers.get("x-api-key") == "sk_test"


# --------------------------------------------------------------------------- async

@pytest.mark.asyncio
async def test_async_retries_on_500_then_succeeds() -> None:
    handler, counter = _sequence_handler(
        [
            httpx.Response(500, json={"detail": "boom"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_async_sleep()
    transport = AsyncRetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.5, jitter=0.0),
        sleep=sleep,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 200
    assert counter.n == 2
    assert delays == [0.5]


@pytest.mark.asyncio
async def test_async_retry_after_header_honored() -> None:
    handler, _ = _sequence_handler(
        [
            httpx.Response(429, json={"detail": "rl"}, headers={"Retry-After": "4"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_async_sleep()
    transport = AsyncRetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.5, jitter=0.0),
        sleep=sleep,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 200
    assert delays == [4.0]


@pytest.mark.asyncio
async def test_async_does_not_retry_on_409() -> None:
    handler, counter = _sequence_handler(
        [
            httpx.Response(409, json={"detail": "already done"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    delays, sleep = _capturing_async_sleep()
    transport = AsyncRetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=3, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get("https://proto-tools.evodesign.org/x")
    assert resp.status_code == 409
    assert counter.n == 1
    assert delays == []


@pytest.mark.asyncio
async def test_async_max_retries_cap_on_exceptions() -> None:
    handler, counter = _sequence_handler([httpx.ConnectError("down")] * 10)
    delays, sleep = _capturing_async_sleep()
    transport = AsyncRetryTransport(
        httpx.MockTransport(handler),
        RetryConfig(max_retries=2, initial_delay=0.01, jitter=0.0),
        sleep=sleep,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get("https://proto-tools.evodesign.org/x")
    assert counter.n == 3
    assert len(delays) == 2
