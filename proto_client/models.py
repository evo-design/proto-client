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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator

__all__ = [
    # Tools API models
    "BatchItemFailure",
    "BatchItemSuccess",
    "BatchResult",
    "JobResponse",
    "JobStatus",
    "JobStatusResponse",
    "ToolExample",
    "ToolInfo",
    "ToolSchema",
    # Runs / language API models
    "CancelDetails",
    "CancelRunResponse",
    "ConstraintResult",
    "ConstraintSpec",
    "ConstructResult",
    "CreateRunResponse",
    "GeneratorSpec",
    "MeResponse",
    "MetricPoint",
    "OptimizerSpec",
    "PaginatedTimepoints",
    "ProposalResult",
    "ResultEntry",
    "RunResponse",
    "RunStatus",
    "RunTimepointResponse",
    "SegmentResult",
    "StageMetrics",
    "StageResult",
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
    label: str
    category: str
    description: str
    uses_gpu: bool
    github_url: str | None = None
    paper_url: str | None = None
    image_url: str | None = None
    organizations: list[str] | None = None
    docs_url: str | None = None
    citation: str | None = None
    example_notebook_url: str | None = None
    iterable_input_field: str | None = None
    iterable_output_field: str | None = None


class ToolExample(BaseModel):
    """A tool's minimal valid input dict from ``GET /api/v1/tools/{key}/example``.

    ``example_input`` is ``None`` when the tool's spec doesn't define one.
    """

    model_config = ConfigDict(frozen=True)

    example_input: dict[str, Any] | None = None


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


class BatchItemSuccess(BaseModel):
    """A single succeeded item from a batch run.

    ``output`` is ``dict[str, Any]`` by default. When ``output_model`` is
    passed to :meth:`~proto_client.tools.ToolsNamespace.run_batch`, it
    becomes an instance of that model at runtime (same swap pattern as
    :attr:`JobStatusResponse.result`).
    """

    model_config = ConfigDict(frozen=True)

    index: int
    status: Literal["succeeded"] = "succeeded"
    output: Any


class BatchItemFailure(BaseModel):
    """A single failed item from a batch run."""

    model_config = ConfigDict(frozen=True)

    index: int
    status: Literal["failed"] = "failed"
    error: str


BatchItem = Annotated[BatchItemSuccess | BatchItemFailure, Discriminator("status")]


class BatchResult(BaseModel):
    """Structured result from a batch tool run.

    Each item in ``items`` is either a :class:`BatchItemSuccess` or
    :class:`BatchItemFailure`, discriminated on the ``status`` field.
    """

    model_config = ConfigDict(frozen=True)

    items: list[BatchItem]

    @property
    def succeeded(self) -> list[BatchItemSuccess]:
        """Items that completed successfully."""
        return [it for it in self.items if isinstance(it, BatchItemSuccess)]

    @property
    def failed(self) -> list[BatchItemFailure]:
        """Items that failed."""
        return [it for it in self.items if isinstance(it, BatchItemFailure)]

    @property
    def errors(self) -> dict[int, str]:
        """Map of input index to error message for failed items."""
        return {it.index: it.error for it in self.failed}

    def get_output(self, index: int) -> Any:
        """Get the output for a specific input index, or ``None`` if it failed."""
        for it in self.succeeded:
            if it.index == index:
                return it.output
        return None

    def get_error(self, index: int) -> str | None:
        """Get the error for a specific input index, or ``None`` if it succeeded."""
        for it in self.failed:
            if it.index == index:
                return it.error
        return None


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
    """Result from ``POST /programs/validate``."""

    model_config = ConfigDict(frozen=True)

    valid: bool
    message: str


class MeResponse(BaseModel):
    """Self-describing principal payload from ``GET /api/v1/me``.

    The capability list is the server's source of truth — clients should
    read this once at boot rather than re-exporting the same strings as
    a separate env var. ``is_master`` is set when the request key matched
    the dev master-key escape hatch on the server; master principals
    bypass every capability check, so callers should treat ``is_master``
    as "all capabilities granted" without inspecting the list.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str
    label: str
    capabilities: list[str]
    is_master: bool


class CancelDetails(BaseModel):
    """Per-cancel-call detail flags returned alongside :class:`CancelRunResponse`."""

    model_config = ConfigDict(frozen=True)

    already_cancelled: bool = False
    task_terminated: bool = False
    note: str | None = None


class CancelRunResponse(BaseModel):
    """Result from ``POST /runs/{run_id}/cancel``."""

    model_config = ConfigDict(frozen=True)

    message: str
    status: RunStatus
    details: CancelDetails


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


class MetricPoint(BaseModel):
    """A single decimated point — one ``(timepoint, result_idx, energy)`` row."""

    model_config = ConfigDict(frozen=True)

    timepoint: int
    result_idx: int
    energy_score: float | None = None


class StageMetrics(BaseModel):
    """Decimated energy series for one optimizer stage."""

    model_config = ConfigDict(frozen=True)

    optimizer_stage_idx: int
    points: list[MetricPoint]


class PaginatedTimepoints(BaseModel):
    """One page of full timepoint rows plus the run-wide total."""

    model_config = ConfigDict(frozen=True)

    items: list[RunTimepointResponse]
    total: int
    page: int
    page_size: int


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
