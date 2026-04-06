"""Typed event models for SSE run streams.

The the runs API streams optimization run progress via
``GET /events?run_id=...`` as Server-Sent Events. Each SSE event has an
``event`` field (the type tag) and a ``data`` field (JSON payload). This
module maps those into typed Pydantic models with ``Literal`` type
discriminators for clean ``match event.type:`` pattern matching.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunEvent(BaseModel):
    """Base class for all run stream events.

    Every event carries a ``.type`` discriminator, a ``.run_id``, and the
    full parsed JSON in ``.data`` for forward-compatible access to fields
    not yet modelled.
    """

    model_config = ConfigDict(frozen=True)

    type: str
    run_id: str
    timestamp: str | None = None
    data: dict[str, Any]


class ProgressEvent(RunEvent):
    """Optimization step update — emitted after each timepoint."""

    type: Literal["progress"] = "progress"
    progress_percent: float | None = None
    optimizer_stage_idx: int = 0
    total_stages: int | None = None
    results: list[Any] = Field(default_factory=list)
    proposal_results: list[Any] = Field(default_factory=list)


class StageCompleteEvent(RunEvent):
    """A single optimization stage finished."""

    type: Literal["stage_complete"] = "stage_complete"
    optimizer_stage_idx: int = 0
    best_result_idx: int = 0
    results: list[Any] = Field(default_factory=list)


class CompletedEvent(RunEvent):
    """Entire run finished successfully."""

    type: Literal["completed"] = "completed"
    stage_results: list[Any] = Field(default_factory=list)


class FailedEvent(RunEvent):
    """Run encountered an error."""

    type: Literal["failed"] = "failed"
    error_message: str | None = None


class CancelledEvent(RunEvent):
    """Run was cancelled by the user."""

    type: Literal["cancelled"] = "cancelled"


_EVENT_CLASSES: dict[str, type[RunEvent]] = {
    "progress": ProgressEvent,
    "stage_complete": StageCompleteEvent,
    "completed": CompletedEvent,
    "failed": FailedEvent,
    "cancelled": CancelledEvent,
}


def parse_sse_event(event_type: str | None, data: dict[str, Any]) -> RunEvent | None:
    """Parse a raw SSE event into a typed :class:`RunEvent` subclass.

    Returns ``None`` for the ``connected`` keep-alive event and any
    unrecognised event types (forward-compatible — the server may add new
    types before the SDK is updated).
    """
    if event_type is None or event_type == "connected":
        return None
    cls = _EVENT_CLASSES.get(event_type)
    if cls is None:
        return None
    return cls(
        run_id=data["run_id"],
        timestamp=data.get("timestamp"),
        data=data,
        **{k: v for k, v in data.items() if k in cls.model_fields and k not in ("type", "run_id", "timestamp", "data")},
    )


__all__ = [
    "CancelledEvent",
    "CompletedEvent",
    "FailedEvent",
    "ProgressEvent",
    "RunEvent",
    "StageCompleteEvent",
    "parse_sse_event",
]
