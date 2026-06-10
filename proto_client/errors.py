"""Typed error hierarchy for Proto API responses.

Every error carries ``status_code``, ``message``, and ``request_id``. The
``from_response`` factory maps an ``httpx.Response`` to the appropriate
subclass — call sites replace ``response.raise_for_status()`` with::

    if response.is_error:
        raise errors.from_response(response)
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


class ProtoAPIError(Exception):
    """Base class for all Proto API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: str | None = None,
    ) -> None:
        """Initialize with status code, message, and optional request ID."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.request_id = request_id

    def __str__(self) -> str:
        tail = f" [request_id={self.request_id}]" if self.request_id else ""
        return f"[{self.status_code}] {self.message}{tail}"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code}, "
            f"message={self.message!r}, request_id={self.request_id!r})"
        )


class ProtoAuthError(ProtoAPIError):
    """401/403 — invalid or missing API key."""


class ProtoNotFoundError(ProtoAPIError):
    """404 — resource not found."""


class ProtoConflictError(ProtoAPIError):
    """409 — request conflicts with current resource state.

    Examples: cancelling a job that has already completed, or reusing an
    ``Idempotency-Key`` with different inputs than the original request.
    """


class ProtoValidationError(ProtoAPIError):
    """422 — request failed server-side validation.

    ``errors`` mirrors FastAPI's ``detail`` list — each entry has
    ``loc``, ``msg``, ``type`` keys.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize with optional structured validation errors."""
        super().__init__(message, status_code=status_code, request_id=request_id)
        self.errors: list[dict[str, Any]] = errors or []


class ProtoRateLimitError(ProtoAPIError):
    """429 — rate limited. ``retry_after`` is parsed from ``Retry-After``."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Initialize with optional retry-after delay from server."""
        super().__init__(message, status_code=status_code, request_id=request_id)
        self.retry_after = retry_after


class ProtoServerError(ProtoAPIError):
    """5xx — server-side failure (retriable)."""


class RunFailedError(RuntimeError):
    """An optimization run ended with status ``failed``."""

    def __init__(self, run_id: str, error_message: str | None) -> None:
        """Initialize with run ID and server error message."""
        self.run_id = run_id
        self.error_message = error_message
        super().__init__(f"Run {run_id} failed: {error_message}")


class RunCancelledError(RuntimeError):
    """An optimization run was cancelled."""

    def __init__(self, run_id: str) -> None:
        """Initialize with run ID."""
        self.run_id = run_id
        super().__init__(f"Run {run_id} was cancelled")


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value.

    Accepts either a numeric delta-seconds or an HTTP-date. Returns ``None``
    when the value is missing or unparseable. Negative numeric values and
    past HTTP-dates both clamp to ``0.0`` so callers don't end up sleeping a
    negative duration.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


def _extract_body(response: httpx.Response) -> Any:
    try:
        response.read()  # ensure stream is consumed before parsing
        return response.json()
    except Exception:
        return None


def _extract_message(body: Any, status_code: int) -> str:
    # FastAPI: {"detail": "..."} for string HTTPException, or
    # {"detail": [{loc, msg, type}, ...]} for RequestValidationError.
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg")
                if isinstance(msg, str):
                    return msg
            return "Validation error"
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
    return f"HTTP {status_code}"


def _extract_validation_errors(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, list):
            return [e for e in detail if isinstance(e, dict)]
    return []


def from_response(response: httpx.Response) -> ProtoAPIError:
    """Map an ``httpx.Response`` with a non-2xx status to a typed error."""
    status = response.status_code
    request_id = response.headers.get("X-Request-ID")
    body = _extract_body(response)
    message = _extract_message(body, status)

    if status in (401, 403):
        return ProtoAuthError(message, status_code=status, request_id=request_id)
    if status == 404:
        return ProtoNotFoundError(message, status_code=status, request_id=request_id)
    if status == 409:
        return ProtoConflictError(message, status_code=status, request_id=request_id)
    if status == 422:
        return ProtoValidationError(
            message,
            status_code=status,
            request_id=request_id,
            errors=_extract_validation_errors(body),
        )
    if status == 429:
        return ProtoRateLimitError(
            message,
            status_code=status,
            request_id=request_id,
            retry_after=parse_retry_after(response.headers.get("Retry-After")),
        )
    if 500 <= status < 600:
        return ProtoServerError(message, status_code=status, request_id=request_id)
    return ProtoAPIError(message, status_code=status, request_id=request_id)


__all__ = [
    "ProtoAPIError",
    "ProtoAuthError",
    "ProtoConflictError",
    "ProtoNotFoundError",
    "ProtoRateLimitError",
    "ProtoServerError",
    "ProtoValidationError",
    "RunCancelledError",
    "RunFailedError",
    "from_response",
    "parse_retry_after",
]
