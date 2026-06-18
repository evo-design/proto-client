"""Proto Bio Python SDK."""

import logging
import os

from proto_client._async.client import AsyncProtoClient
from proto_client.client import ProtoClient
from proto_client.errors import (
    JobCancelledError,
    JobFailedError,
    ProtoAPIError,
    ProtoAuthError,
    ProtoConflictError,
    ProtoError,
    ProtoNotFoundError,
    ProtoRateLimitError,
    ProtoServerError,
    ProtoValidationError,
    RunCancelledError,
    RunFailedError,
)
from proto_client.models import (
    AssetRef,
    BatchItemFailure,
    BatchItemSuccess,
    BatchResult,
    CancelDetails,
    CancelRunResponse,
    ConstraintResult,
    ConstraintSpec,
    ConstructListItem,
    ConstructResult,
    CreateRunResponse,
    GeneratorSpec,
    JobResponse,
    JobStatus,
    JobStatusResponse,
    Level,
    LogRecord,
    LogsEnd,
    LogsPage,
    MeResponse,
    MetricPoint,
    OptimizerSpec,
    PaginatedTimepoints,
    ProposalResult,
    ResultEntry,
    ResultEntryListItem,
    RunResponse,
    RunStatus,
    RunTimepointListItem,
    RunTimepointResponse,
    SegmentListItem,
    SegmentResult,
    StageMetrics,
    StageResult,
    StreamChannel,
    ToolExample,
    ToolInfo,
    ToolSchema,
    ValidationResponse,
)
from proto_client.utils.asset_helpers import AssetLike, coerce_assetref, is_assetref
from proto_client.utils.http import RetryConfig
from proto_client.utils.version import VERSION as __version__

__all__ = [
    "__version__",
    "AsyncProtoClient",
    "AssetLike",
    "AssetRef",
    "BatchItemFailure",
    "BatchItemSuccess",
    "BatchResult",
    "CancelDetails",
    "CancelRunResponse",
    "ConstraintResult",
    "ConstraintSpec",
    "ConstructListItem",
    "ConstructResult",
    "CreateRunResponse",
    "GeneratorSpec",
    "JobCancelledError",
    "JobFailedError",
    "JobResponse",
    "JobStatus",
    "JobStatusResponse",
    "Level",
    "LogRecord",
    "LogsEnd",
    "LogsPage",
    "MeResponse",
    "MetricPoint",
    "OptimizerSpec",
    "PaginatedTimepoints",
    "ProposalResult",
    "ProtoAPIError",
    "ProtoAuthError",
    "ProtoClient",
    "ProtoConflictError",
    "ProtoError",
    "ProtoNotFoundError",
    "ProtoRateLimitError",
    "ProtoServerError",
    "ProtoValidationError",
    "ResultEntry",
    "ResultEntryListItem",
    "RetryConfig",
    "RunCancelledError",
    "RunFailedError",
    "RunResponse",
    "RunStatus",
    "RunTimepointListItem",
    "RunTimepointResponse",
    "SegmentListItem",
    "SegmentResult",
    "StageMetrics",
    "StageResult",
    "StreamChannel",
    "ToolExample",
    "ToolInfo",
    "ToolSchema",
    "ValidationResponse",
    "coerce_assetref",
    "is_assetref",
]

_logger = logging.getLogger("proto_client")
_logger.addHandler(logging.NullHandler())

_log_level = os.environ.get("PROTO_LOG", "").lower()
if _log_level in ("debug", "info"):
    _logger.setLevel(getattr(logging, _log_level.upper()))
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)
