"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from model_regression_detection.config import Environment
from model_regression_detection.domain.versions import TargetKind
from model_regression_detection.specification.models import EvaluationSpecification


class LiveResponse(BaseModel):
    """Liveness response containing no dependency or secret information."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str
    environment: Environment
    timestamp: datetime
    supported_target_kinds: tuple[TargetKind, ...]


class ReadyResponse(BaseModel):
    """Readiness response reflecting required dependency availability."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable", "not_configured"]


class RunCreateCommand(BaseModel):
    """Request body to submit an immutable evaluation run."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    specification: EvaluationSpecification


class RunCreateResponse(BaseModel):
    """Response returned after a run is accepted and its snapshot is frozen."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str
    suite: str
    state: Literal["created"]
    configuration_hash: str
    dataset_hash: str


class RunStatusResponse(BaseModel):
    """Current status of a persisted run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str
    suite: str
    state: Literal["created", "running", "completed", "failed", "cancelling", "cancelled"]
    gate_outcome: Literal["pass", "fail", "error"] | None
    total_cases: int | None
    created_at: datetime
    completed_at: datetime | None


class CancelRunResponse(BaseModel):
    """Response after a cancellation request is processed."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    state: Literal["cancelling", "cancelled"]
    already_cancelled: bool


class CaseEvidenceResponse(BaseModel):
    """Minimal case-level evidence for the full run report."""

    model_config = ConfigDict(extra="forbid")

    case_key: str
    ordinal: Annotated[int, Field(ge=0)]
    outcome: str
    provider_status: str
    cost: float | None
    evidence: dict[str, Any]


class RunReportResponse(BaseModel):
    """Full run report including case-level evidence."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str
    suite: str
    state: Literal["created", "running", "completed", "failed", "cancelling", "cancelled"]
    gate_outcome: Literal["pass", "fail", "error"] | None
    total_cases: int | None
    metrics: dict[str, Any] | None
    cases: tuple[CaseEvidenceResponse, ...]
    created_at: datetime
    completed_at: datetime | None
