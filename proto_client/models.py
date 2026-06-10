"""Response models for the Proto Bio SDK.

Thin wire-shape mirrors of ``the tools API`` / ``the runs API``.
:class:`AssetRef` is a pure data model carrying only ``_repr_html_`` (a Jupyter
card); fetching an asset's bytes goes through the ``client.assets`` namespace
(``get`` / ``decode`` / ``download``), not the ref itself.

Tool-specific input/output dicts stay ``dict[str, Any]``; pass ``output_model``
to :meth:`proto_client.tools.ToolsNamespace.run` for a typed ``.result``.
"""

import html
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field

__all__ = [
    # Shared API models
    "AssetRef",
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
    "ConstructListItem",
    "ConstructResult",
    "CreateRunResponse",
    "GeneratorSpec",
    "MeResponse",
    "MetricPoint",
    "OptimizerSpec",
    "PaginatedTimepoints",
    "ProposalResult",
    "ResultEntry",
    "ResultEntryListItem",
    "RunResponse",
    "RunStatus",
    "RunTimepointListItem",
    "RunTimepointResponse",
    "SegmentListItem",
    "SegmentResult",
    "StageMetrics",
    "StageResult",
    "ValidationResponse",
    # Logs (shared by runs + tools jobs)
    "Level",
    "LogRecord",
    "LogsEnd",
    "LogsPage",
    "StreamChannel",
]


class JobStatus(str, Enum):
    """Lifecycle states for a tool execution job."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AssetRef(BaseModel):
    """Storage-neutral reference to API-managed asset bytes."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    kind: Literal["output", "reference_db", "user_upload"]
    mime_type: str | None = None
    size_bytes: int | None = None
    filename: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    url: str | None = None

    def suggested_filename(self) -> str:
        """Filename for local materialization, with path components stripped to prevent traversal."""
        from proto_client.utils.asset_helpers import ext_for_mime

        if self.filename:
            safe = Path(self.filename).name
            if safe and safe not in (".", ".."):
                return safe
        safe_id = Path(self.id).name or self.id
        return f"{safe_id}{ext_for_mime(self.mime_type)}"

    def _repr_html_(self) -> str:
        """Compact inline card for Jupyter; all interpolated values escaped against XSS."""
        size = self.size_bytes
        if size is None:
            size_str = ""
        elif size >= 1_000_000:
            size_str = f" · {size / 1_000_000:.1f} MB"
        elif size >= 1_000:
            size_str = f" · {size / 1_000:.1f} KB"
        else:
            size_str = f" · {size} B"
        mime = html.escape(self.mime_type or "unknown")
        link = f'<a href="{html.escape(self.url, quote=True)}" target="_blank">download</a>' if self.url else "(no url)"
        return (
            '<div style="font-family:monospace;border-left:3px solid #888;padding:4px 8px">'
            f"<strong>AssetRef</strong> · {mime}{size_str} · {link}<br>"
            f"<small>{html.escape(self.id)}</small></div>"
        )


class ToolInfo(BaseModel):
    """Tool metadata from ``GET /api/v1/tools``.

    ``service`` and ``method`` are ``None`` for inline (in-process) tools and
    for unhosted tools (``hosted=False``); the latter also carry
    ``unhosted_reason``. Mirrors the tools API's ``ToolInfo``.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    service: str | None = None
    method: str | None = None
    label: str
    category: str
    description: str
    uses_gpu: bool
    hosted: bool
    unhosted_reason: str | None = None
    source_url: str
    github_url: str | None = None
    paper_url: str | None = None
    image_url: str | None = None
    organizations: list[str] | None = None
    docs_url: str | None = None
    citation: str | None = None
    example_notebook_url: str | None = None
    iterable_input_fields: list[str] | None = None
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


class SegmentListItem(BaseModel):
    """Slim per-segment row without per-constraint scores."""

    model_config = ConfigDict(frozen=True)

    label: str
    length: int
    sequence: str


class ConstructListItem(BaseModel):
    """Slim per-construct row without per-constraint scores."""

    model_config = ConfigDict(frozen=True)

    label: str
    type: str
    segments: list[SegmentListItem]


class ResultEntryListItem(BaseModel):
    """Slim per-result row without per-constraint scores."""

    model_config = ConfigDict(frozen=True)

    result_idx: int
    energy_score: float | None = None
    constructs: list[ConstructListItem]


class StageResult(BaseModel):
    """Slim per-stage rollup returned by ``GET /runs/{id}``."""

    model_config = ConfigDict(frozen=True)

    optimizer_stage_idx: int
    best_result_idx: int
    results: list[ResultEntryListItem]


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

    Lets a client introspect its workspace + scopes without a second
    round-trip; read once at boot rather than caching a hand-rolled mirror.
    Mirrors the runs API's ``MeResponse``.

    Attributes:
        workspace_id (str): The caller's workspace UUID.
        workspace_name (str): Human-readable workspace name.
        key_id (str): The resolving API key's id.
        scopes (list[str]): Granted scopes — ``full`` (read + dispatch) or ``read_only``.
        member_user_id (str | None): The member user id for proxy/browser callers; ``None`` for raw API keys.
        tier (str): ``preview`` (examples-only, no authoring) or ``expanded`` (can author).
        credit_cap (float | None): Credit ceiling, or ``None`` when uncapped.
        remaining_credits (float | None): Remaining credits (cap minus spend), floored at 0, or ``None`` when uncapped.
    """

    model_config = ConfigDict(frozen=True)

    workspace_id: str
    workspace_name: str
    key_id: str
    scopes: list[str]
    member_user_id: str | None = None
    tier: str
    credit_cap: float | None = None
    remaining_credits: float | None = None


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


class RunTimepointListItem(BaseModel):
    """Slim timepoint row returned by ``GET /runs/{id}/timepoints``."""

    model_config = ConfigDict(frozen=True)

    id: int
    run_id: str
    optimizer_stage_idx: int
    timepoint: int
    best_result_idx: int
    results: list[ResultEntryListItem]
    optimizer_metadata: dict[str, Any] | None = None
    created_at: datetime


class PaginatedTimepoints(BaseModel):
    """One page of slim timepoint rows plus the run-wide total."""

    model_config = ConfigDict(frozen=True)

    items: list[RunTimepointListItem]
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


# ---------------------------------------------------------------------------
# Logs — shared by runs and tools jobs
# ---------------------------------------------------------------------------


#: RFC 5424 severity carried by every :class:`LogRecord`.
Level = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]

#: Source channel for a :class:`LogRecord` (orthogonal to ``Level``).
StreamChannel = Literal["stdout", "stderr", "system"]


class LogRecord(BaseModel):
    """A single NDJSON log line. ``stream`` is the channel; ``level`` is the RFC 5424 severity (orthogonal)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["record"] = "record"
    seq: int
    ts: datetime
    stream: StreamChannel
    level: Level
    msg: str


class LogsEnd(BaseModel):
    """Typed terminator emitted as the last NDJSON line of a log stream."""

    model_config = ConfigDict(frozen=True)

    type: Literal["end"] = "end"
    reason: Literal["completed", "truncated", "idle_timeout"]
    final_seq: int


class LogsPage(BaseModel):
    """A batch of :class:`LogRecord` rows; ``next_since`` resumes the stream, ``end_reason`` is set once it terminates."""

    model_config = ConfigDict(frozen=True)

    records: list[LogRecord]
    next_since: int | None = None
    end_reason: Literal["completed", "truncated", "idle_timeout"] | None = None
