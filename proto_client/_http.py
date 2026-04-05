"""Retry-aware httpx transports (sync + async).

Wrap an existing ``httpx.BaseTransport`` / ``httpx.AsyncBaseTransport`` so
failed requests are retried with exponential backoff + jitter. Retriable:
429, 500, 502, 503, 504, and connection/read-timeout errors. Non-retriable
client errors (400, 401, 403, 404, 409, 422) fall through unchanged — the
caller will map them to typed errors via ``proto_client.errors.from_response``.

On 429, if the server emits a ``Retry-After`` header we honor it verbatim
instead of computed backoff. Conservative defaults (``max_retries=2``) keep
the SDK from amplifying 429 storms against the the tools API rate limiter.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from proto_client.errors import parse_retry_after

RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
)


@dataclass(frozen=True)
class RetryConfig:
    """Tunables for :class:`RetryTransport` / :class:`AsyncRetryTransport`.

    ``max_retries`` is the number of *additional* attempts after the first
    — ``max_retries=2`` yields up to 3 total requests.
    """

    max_retries: int = 2
    initial_delay: float = 0.5
    max_delay: float = 30.0
    factor: float = 2.0
    jitter: float = 0.1  # fractional, ±10% of the computed base delay

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be >= 0")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")
        if self.factor < 1.0:
            raise ValueError("factor must be >= 1.0")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter must be in [0, 1]")


def compute_backoff(
    attempt: int,
    config: RetryConfig,
    rng: random.Random | None = None,
) -> float:
    """Exponential backoff with symmetric jitter.

    ``attempt`` is 0-indexed (0 = delay before the *first* retry). Exposed
    for tests so we can seed the RNG and assert delays fall in the expected
    window.
    """
    base = min(config.initial_delay * (config.factor**attempt), config.max_delay)
    if config.jitter == 0.0:
        return base
    spread = base * config.jitter
    r = rng or random
    return max(0.0, base + r.uniform(-spread, spread))


def _delay_for_response(
    response: httpx.Response,
    attempt: int,
    config: RetryConfig,
    rng: random.Random | None = None,
) -> float:
    """Compute the wait before the next attempt given a retriable response."""
    if response.status_code == 429:
        server_hint = parse_retry_after(response.headers.get("Retry-After"))
        if server_hint is not None:
            return server_hint
    return compute_backoff(attempt, config, rng=rng)


class RetryTransport(httpx.BaseTransport):
    """Sync retry wrapper. Delegates transport to ``wrapped``.

    Arbitrary request headers — including ``x-app-user-id`` for per-user
    rate-limit isolation — pass through unchanged; this transport never
    inspects or mutates request headers.
    """

    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        config: RetryConfig | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._config = config or RetryConfig()
        self._sleep = sleep or time.sleep
        self._rng = rng

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        config = self._config
        attempt = 0
        while True:
            try:
                response = self._wrapped.handle_request(request)
            except RETRYABLE_EXCEPTIONS:
                if attempt >= config.max_retries:
                    raise
                self._sleep(compute_backoff(attempt, config, rng=self._rng))
                attempt += 1
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= config.max_retries:
                return response

            delay = _delay_for_response(response, attempt, config, rng=self._rng)
            # Drop the stream before retrying so httpx can reuse the conn.
            response.close()
            self._sleep(delay)
            attempt += 1

    def close(self) -> None:
        self._wrapped.close()


class AsyncRetryTransport(httpx.AsyncBaseTransport):
    """Async retry wrapper — behaviorally identical to :class:`RetryTransport`."""

    def __init__(
        self,
        wrapped: httpx.AsyncBaseTransport,
        config: RetryConfig | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._config = config or RetryConfig()
        self._sleep = sleep or asyncio.sleep
        self._rng = rng

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        config = self._config
        attempt = 0
        while True:
            try:
                response = await self._wrapped.handle_async_request(request)
            except RETRYABLE_EXCEPTIONS:
                if attempt >= config.max_retries:
                    raise
                await self._sleep(compute_backoff(attempt, config, rng=self._rng))
                attempt += 1
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= config.max_retries:
                return response

            delay = _delay_for_response(response, attempt, config, rng=self._rng)
            await response.aclose()
            await self._sleep(delay)
            attempt += 1

    async def aclose(self) -> None:
        await self._wrapped.aclose()


__all__ = [
    "AsyncRetryTransport",
    "RETRYABLE_EXCEPTIONS",
    "RETRYABLE_STATUS",
    "RetryConfig",
    "RetryTransport",
    "compute_backoff",
]
