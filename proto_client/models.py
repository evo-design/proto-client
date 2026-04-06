"""Response models for the Proto Bio SDK.

These mirror the wire shapes returned by ``the tools API`` 1:1. They are
intentionally thin — no business logic — so they can be regenerated from
OpenAPI in the future without behaviour drift.

Tool-specific input/output dicts are left as ``dict[str, Any]`` because every
tool has its own ``Input``/``Config``/``Output`` models in ``proto-tools``;
a single static type here would be a lie. Power users can pass ``output_model``
to :meth:`proto_client.tools.ToolsNamespace.run` to opt into a typed
``.result`` per-call.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = [
    "JobResponse",
    "JobStatus",
    "JobStatusResponse",
    "ToolInfo",
    "ToolSchema",
]


class JobStatus(str, Enum):
    """Lifecycle states for a tool execution job."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ToolInfo(BaseModel):
    """Tool metadata from ``GET /api/v1/tools``."""

    model_config = ConfigDict(frozen=True)

    key: str
    service: str
    method: str


class ToolSchema(BaseModel):
    """JSON schemas for a tool's input, config, and output models.

    Each field is a raw JSON Schema dict (as emitted by Pydantic's
    ``model_json_schema()``), not a parsed model. Returned by
    ``GET /api/v1/tools/{key}/schema``.
    """

    model_config = ConfigDict(frozen=True)

    inputs: dict[str, Any]
    config: dict[str, Any]
    output: dict[str, Any]


class JobResponse(BaseModel):
    """202 submission ack from ``POST /api/v1/tools/{key}/run``."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    """Full job envelope returned by get/cancel/sync-run endpoints.

    ``result`` wire type is ``dict[str, Any] | None``. When the caller passes
    ``output_model=MyModel`` to :meth:`ToolsNamespace.run` (or ``run_batch``),
    the SDK validates ``result`` through that model and swaps the dict for
    the parsed instance post-hoc, so ``response.result`` is an instance of
    ``MyModel`` at runtime. The declared field type stays ``dict | None`` —
    call sites that use ``output_model`` should cast or ``isinstance``-check.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    tool_key: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
