"""Strict versioned JSON report models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from model_regression_detection.domain.versions import VersionedTargetRef
from model_regression_detection.evaluators.models import EvaluationStatus
from model_regression_detection.policy.models import (
    CaseOutcome,
    GateOutcome,
    RuleDecision,
    RunMetrics,
)
from model_regression_detection.providers.contracts import ProviderError
from model_regression_detection.specification.models import EvaluatorType

REPORT_SCHEMA_VERSION: Literal["1"] = "1"


class ReportModel(BaseModel):
    """Strict immutable base for report view models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportProvenance(ReportModel):
    """Immutable identity of everything that produced the report."""

    suite: str
    configuration_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    dataset_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    prompt: VersionedTargetRef
    model: VersionedTargetRef
    agent: VersionedTargetRef | None


class ReportEvaluation(ReportModel):
    """Bounded evaluator evidence for the report."""

    evaluator_name: str
    evaluator_type: EvaluatorType
    status: EvaluationStatus
    explanation: str
    error_code: str | None


class ReportCase(ReportModel):
    """One case entry with bounded output and evaluator evidence."""

    case_key: str
    ordinal: Annotated[int, Field(ge=0)]
    critical: bool
    outcome: CaseOutcome
    provider_status: Literal["success", "error"]
    resolved_model: str | None
    latency_ms: Annotated[float, Field(ge=0.0)]
    output_excerpt: str | None
    provider_error: ProviderError | None
    evaluations: tuple[ReportEvaluation, ...]


class JsonReport(ReportModel):
    """Complete versioned local evaluation report."""

    schema_version: Literal["1"] = REPORT_SCHEMA_VERSION
    generator_version: str
    gate_outcome: GateOutcome
    provenance: ReportProvenance
    metrics: RunMetrics
    rules: tuple[RuleDecision, ...]
    cases: tuple[ReportCase, ...]
    metadata: dict[str, JsonValue]
