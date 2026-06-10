"""Retry-aware httpx transports (sync + async).

Wrap an existing ``httpx.BaseTransport`` / ``httpx.AsyncBaseTransport`` so
failed requests are retried with exponential backoff + jitter. Retriable:
429, 500, 502, 503, 504, and connection/read-timeout errors. Non-retriable
client errors (400, 401, 403, 404, 409, 422) fall through unchanged — the
caller will map them to typed errors via ``proto_client.errors.from_response``.

On 429/503, if the server emits a ``Retry-After`` header we honor it (capped
at ``retry_after_max``) instead of computed backoff. Conservative defaults
(``max_retries=2``) keep the SDK from amplifying 429 storms against the
the tools API rate limiter.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from proto_client.errors import parse_retry_after

logger = logging.getLogger("proto_client.utils.http")

RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
# RemoteProtocolError is retriable (proxy closes stale keep-alives on long polls);
# LocalProtocolError stays non-retriable (deterministic client-side bug).
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True)
class RetryConfig:
    """Tunables for :class:`RetryTransport` / :class:`AsyncRetryTransport`.

    ``max_retries`` is the number of *additional* attempts after the first
    — ``max_retries=2`` yields up to 3 total requests.

    ``retry_after_max`` caps how long an honored server ``Retry-After`` header
    can park a retry, so a hostile or buggy value can't wedge the client for
    hours. It bounds the *server hint* only; ``max_delay`` still bounds our own
    computed backoff.
    """

    max_retries: int = 2
    initial_delay: float = 0.5
    max_delay: float = 30.0
    factor: float = 2.0
    jitter: float = 0.1  # fractional, ±10% of the computed base delay
    retry_after_max: float = 300.0  # cap on an honored server Retry-After (seconds)

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
        if self.retry_after_max < 0:
            raise ValueError("retry_after_max must be >= 0")


def compute_backoff(
    attempt: int,
    config: RetryConfig,
    rng: random.Random | None = None,
) -> float:
    """Exponential backoff with symmetric jitter. ``attempt`` is 0-indexed.

    Accepts an explicit ``rng`` so tests can seed it and assert the sampled
    delay falls inside the jitter window.
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
    # RFC 9110: both 429 and 503 may carry Retry-After.
    if response.status_code in (429, 503):
        server_hint = parse_retry_after(response.headers.get("Retry-After"))
        if server_hint is not None:
            return min(server_hint, config.retry_after_max)
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
        """Wrap *wrapped* with retry behavior; ``sleep`` and ``rng`` are injectable for tests."""
        self._wrapped = wrapped
        self._config = config or RetryConfig()
        self._sleep = sleep or time.sleep
        self._rng = rng

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request, retrying retriable statuses/exceptions with backoff + jitter."""
        config = self._config
        attempt = 0
        while True:
            try:
                response = self._wrapped.handle_request(request)
            except RETRYABLE_EXCEPTIONS:
                if attempt >= config.max_retries:
                    logger.warning(
                        "Max retries (%d) exhausted for %s %s", config.max_retries, request.method, request.url.path
                    )
                    raise
                delay = compute_backoff(attempt, config, rng=self._rng)
                logger.debug(
                    "Retry attempt %d/%d for %s %s (delay=%.2fs)",
                    attempt + 1,
                    config.max_retries,
                    request.method,
                    request.url.path,
                    delay,
                )
                self._sleep(delay)
                attempt += 1
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= config.max_retries:
                logger.warning(
                    "Max retries (%d) exhausted for %s %s", config.max_retries, request.method, request.url.path
                )
                return response

            delay = _delay_for_response(response, attempt, config, rng=self._rng)
            logger.debug(
                "Retry attempt %d/%d for %s %s (delay=%.2fs)",
                attempt + 1,
                config.max_retries,
                request.method,
                request.url.path,
                delay,
            )
            response.read()
            response.close()
            self._sleep(delay)
            attempt += 1

    def close(self) -> None:
        """Close the wrapped transport."""
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
        """Wrap *wrapped* with retry behavior; ``sleep`` and ``rng`` are injectable for tests."""
        self._wrapped = wrapped
        self._config = config or RetryConfig()
        self._sleep = sleep or asyncio.sleep
        self._rng = rng

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Send the request, retrying retriable statuses/exceptions with backoff + jitter."""
        config = self._config
        attempt = 0
        while True:
            try:
                response = await self._wrapped.handle_async_request(request)
            except RETRYABLE_EXCEPTIONS:
                if attempt >= config.max_retries:
                    logger.warning(
                        "Max retries (%d) exhausted for %s %s", config.max_retries, request.method, request.url.path
                    )
                    raise
                delay = compute_backoff(attempt, config, rng=self._rng)
                logger.debug(
                    "Retry attempt %d/%d for %s %s (delay=%.2fs)",
                    attempt + 1,
                    config.max_retries,
                    request.method,
                    request.url.path,
                    delay,
                )
                await self._sleep(delay)
                attempt += 1
                continue

            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt >= config.max_retries:
                logger.warning(
                    "Max retries (%d) exhausted for %s %s", config.max_retries, request.method, request.url.path
                )
                return response

            delay = _delay_for_response(response, attempt, config, rng=self._rng)
            logger.debug(
                "Retry attempt %d/%d for %s %s (delay=%.2fs)",
                attempt + 1,
                config.max_retries,
                request.method,
                request.url.path,
                delay,
            )
            await response.aread()
            await response.aclose()
            await self._sleep(delay)
            attempt += 1

    async def aclose(self) -> None:
        """Close the wrapped transport."""
        await self._wrapped.aclose()
