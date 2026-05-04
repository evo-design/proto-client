"""Proto Bio Python SDK."""

import logging
import os

from proto_client._async.client import AsyncProtoClient
from proto_client._http import RetryConfig
from proto_client._version import VERSION as __version__
from proto_client.client import ProtoClient
from proto_client.errors import (
    ProtoAPIError,
    ProtoAuthError,
    ProtoConflictError,
    ProtoNotFoundError,
    ProtoRateLimitError,
    ProtoServerError,
    ProtoValidationError,
    RunCancelledError,
    RunFailedError,
)
from proto_client.models import (
    BatchItemFailure,
    BatchItemSuccess,
    BatchResult,
    CancelDetails,
    CancelRunResponse,
    ConstraintResult,
    ConstraintSpec,
    ConstructResult,
    CreateRunResponse,
    GeneratorSpec,
    JobResponse,
    JobStatus,
    JobStatusResponse,
    MetricPoint,
    OptimizerSpec,
    PaginatedTimepoints,
    ProposalResult,
    ResultEntry,
    RunResponse,
    RunStatus,
    RunTimepointResponse,
    SegmentResult,
    StageMetrics,
    StageResult,
    ToolInfo,
    ToolSchema,
    ValidationResponse,
)

__all__ = [
    "__version__",
    "AsyncProtoClient",
    "BatchItemFailure",
    "BatchItemSuccess",
    "BatchResult",
    "CancelDetails",
    "CancelRunResponse",
    "ConstraintResult",
    "ConstraintSpec",
    "ConstructResult",
    "CreateRunResponse",
    "GeneratorSpec",
    "JobResponse",
    "JobStatus",
    "JobStatusResponse",
    "MetricPoint",
    "OptimizerSpec",
    "PaginatedTimepoints",
    "ProposalResult",
    "ProtoAPIError",
    "ProtoAuthError",
    "ProtoClient",
    "ProtoConflictError",
    "ProtoNotFoundError",
    "ProtoRateLimitError",
    "ProtoServerError",
    "ProtoValidationError",
    "ResultEntry",
    "RetryConfig",
    "RunCancelledError",
    "RunFailedError",
    "RunResponse",
    "RunStatus",
    "RunTimepointResponse",
    "SegmentResult",
    "StageMetrics",
    "StageResult",
    "ToolInfo",
    "ToolSchema",
    "ValidationResponse",
]

_logger = logging.getLogger("proto_client")
_logger.addHandler(logging.NullHandler())

_log_level = os.environ.get("PROTO_LOG", "").lower()
if _log_level in ("debug", "info"):
    _logger.setLevel(getattr(logging, _log_level.upper()))
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
