"""Response models for the Proto Bio SDK.

These mirror the wire shapes returned by ``the tools API`` and
``the runs API`` 1:1. They are intentionally thin — no business
logic — so they can be regenerated from OpenAPI in the future without
behaviour drift.

Tool-specific input/output dicts are left as ``dict[str, Any]`` because every
tool has its own ``Input``/``Config``/``Output`` models in ``proto-tools``;
a single static type here would be a lie. Power users can pass ``output_model``
to :meth:`proto_client.tools.ToolsNamespace.run` to opt into a typed
``.result`` per-call.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = [
    # Tools API models
    "JobResponse",
    "JobStatus",
    "JobStatusResponse",
    "ToolInfo",
    "ToolSchema",
    # Runs / language API models
    "ConstraintResult",
    "ConstraintSpec",
    "ConstructResult",
    "CreateRunResponse",
    "GeneratorSpec",
    "OptimizerSpec",
    "ProposalResult",
    "ResultEntry",
    "RunResponse",
    "RunStatus",
    "RunTimepointResponse",
    "SegmentResult",
    "StageResult",
    "StageTimepointHistory",
    "ValidationResponse",
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


# ---------------------------------------------------------------------------
# Runs / language API models
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Lifecycle states for an optimization run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ConstraintResult(BaseModel):
    """Per-constraint scoring result embedded in a segment."""

    model_config = ConfigDict(frozen=True)

    score: float | None = None
    weight: float
    weighted_score: float | None = None
    data: dict[str, Any]
    input_segments: list[str] | None = None
    position_in_inputs: int | None = None


class SegmentResult(BaseModel):
    """Per-segment result with sequence and constraint scores."""

    model_config = ConfigDict(frozen=True)

    label: str
    sequence: str
    constraints: dict[str, ConstraintResult]


class ConstructResult(BaseModel):
    """Per-construct result containing its segments."""

    model_config = ConfigDict(frozen=True)

    label: str
    type: str
    segments: list[SegmentResult]


class ResultEntry(BaseModel):
    """A single result within a stage or timepoint."""

    model_config = ConfigDict(frozen=True)

    result_idx: int
    energy_score: float | None = None
    constructs: list[ConstructResult]


class StageResult(BaseModel):
    """Results for one optimizer stage."""

    model_config = ConfigDict(frozen=True)

    optimizer_stage_idx: int
    best_result_idx: int
    results: list[ResultEntry]


class CreateRunResponse(BaseModel):
    """202 ack from ``POST /runs``."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    status: RunStatus
    message: str


class RunResponse(BaseModel):
    """Full run envelope from ``GET /runs/{run_id}``."""

    model_config = ConfigDict(frozen=True)

    id: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_stage: int
    total_stages: int
    stage_results: list[StageResult]
    error_message: str | None = None


class ValidationResponse(BaseModel):
    """Result from ``POST /validate``."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    message: str


class ProposalResult(BaseModel):
    """A proposal evaluated during optimization."""

    model_config = ConfigDict(frozen=True)

    proposal_idx: int
    accepted: bool
    rejected_by: str | None = None
    energy_score: float | None = None
    constructs: list[ConstructResult]


class RunTimepointResponse(BaseModel):
    """A single optimization timepoint snapshot."""

    model_config = ConfigDict(frozen=True)

    id: int
    run_id: str
    optimizer_stage_idx: int
    timepoint: int
    best_result_idx: int
    results: list[ResultEntry]
    proposal_results: list[ProposalResult] | None = None
    created_at: datetime


class StageTimepointHistory(BaseModel):
    """Timepoint history for one optimizer stage."""

    model_config = ConfigDict(frozen=True)

    optimizer_stage_idx: int
    timepoints: list[RunTimepointResponse]


class ConstraintSpec(BaseModel):
    """Constraint metadata from ``GET /constraints``."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str
    uses_gpu: bool
    config_model: dict[str, Any]
    tools_called: list[str]
    category: str | None = None
    supported_sequence_types: list[str]
    num_input_sequences_per_tuple: int | None = None


class GeneratorSpec(BaseModel):
    """Generator metadata from ``GET /generators``."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str
    uses_gpu: bool
    config_model: dict[str, Any]
    category: str
    tools_called: list[str]
    supported_sequence_types: list[str]


class OptimizerSpec(BaseModel):
    """Optimizer metadata from ``GET /optimizers``."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    description: str
    uses_gpu: bool
    config_model: dict[str, Any]
    targets_single_segment: bool
