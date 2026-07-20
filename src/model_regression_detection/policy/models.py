"""Strict aggregate and fixed-policy decision models."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyModel(BaseModel):
    """Strict immutable base for deterministic derived evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseOutcome(StrEnum):
    """Quality/execution outcome of one golden case."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class GateOutcome(StrEnum):
    """Deployment-gate outcome separate from run execution state."""

    PASS = "pass"  # noqa: S105 - gate outcome label, not a credential
    FAIL = "fail"
    ERROR = "error"


class RuleStatus(StrEnum):
    """Outcome of one ordered fixed-policy rule."""

    PASSED = "passed"
    VIOLATED = "violated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class CaseSummary(PolicyModel):
    """Derived terminal case outcome and evaluator counts."""

    case_key: str
    critical: bool
    outcome: CaseOutcome
    passed_evaluators: Annotated[int, Field(ge=0)]
    failed_evaluators: Annotated[int, Field(ge=0)]
    errored_evaluators: Annotated[int, Field(ge=0)]
    not_applicable_evaluators: Annotated[int, Field(ge=0)]


class RunMetrics(PolicyModel):
    """Deterministic aggregate metrics for one local run."""

    total_cases: Annotated[int, Field(ge=1)]
    passed_cases: Annotated[int, Field(ge=0)]
    failed_cases: Annotated[int, Field(ge=0)]
    error_cases: Annotated[int, Field(ge=0)]
    pass_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    error_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    critical_failed_cases: tuple[str, ...]
    critical_error_cases: tuple[str, ...]
    total_latency_ms: Annotated[float, Field(ge=0.0)]
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    cases_with_unknown_usage: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_counts(self) -> "RunMetrics":
        """Ensure aggregate counts and token totals reconcile."""
        if self.passed_cases + self.failed_cases + self.error_cases != self.total_cases:
            raise ValueError("case outcome counts must equal total_cases")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class RuleDecision(PolicyModel):
    """One ordered, explainable policy decision."""

    rule_id: str
    status: RuleStatus
    observed: float | int | bool | None
    threshold: float | int | bool | None
    unit: Literal["ratio", "count", "boolean", "percent"]
    explanation: str
    affected_cases: tuple[str, ...] = ()


class BaselineComparison(PolicyModel):
    """Deterministic deltas between a baseline run and a candidate run."""

    configuration_match: bool
    dataset_match: bool
    total_cases_candidate: Annotated[int, Field(ge=0)]
    total_cases_baseline: Annotated[int, Field(ge=0)]
    matching_case_keys: tuple[str, ...]
    missing_in_candidate: tuple[str, ...]
    missing_in_baseline: tuple[str, ...]
    pass_rate_baseline: float | None = None
    pass_rate_candidate: float | None = None
    pass_rate_drop: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    latency_ms_baseline: float
    latency_ms_candidate: float
    latency_increase_pct: Annotated[float, Field(ge=0.0)]
    cost_baseline: float | None = None
    cost_candidate: float | None = None
    cost_increase_pct: Annotated[float | None, Field(ge=0.0)] = None


class GateDecision(PolicyModel):
    """Final local gate decision with deterministic rule order and evidence."""

    engine_version: Literal["1"] = "1"
    outcome: GateOutcome
    metrics: RunMetrics
    cases: tuple[CaseSummary, ...]
    rules: tuple[RuleDecision, ...]
