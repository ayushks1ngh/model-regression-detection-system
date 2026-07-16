"""Normalized evaluator evidence models."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from model_regression_detection.specification.models import EvaluatorType


class EvaluationStatus(StrEnum):
    """Terminal status of one evaluator application."""

    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    NOT_APPLICABLE = "not_applicable"


class EvaluationResult(BaseModel):
    """Bounded deterministic evidence for one case evaluator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluator_name: Annotated[str, Field(min_length=1, max_length=128)]
    evaluator_type: EvaluatorType
    status: EvaluationStatus
    explanation: Annotated[str, Field(min_length=1, max_length=2_000)]
    expected: JsonValue | None = None
    observed: JsonValue | None = None
    error_code: Annotated[str | None, Field(max_length=100)] = None

    @model_validator(mode="after")
    def validate_error(self) -> "EvaluationResult":
        """Require error codes only for errored evaluator outcomes."""
        if self.status is EvaluationStatus.ERRORED and self.error_code is None:
            raise ValueError("errored evaluation requires error_code")
        if self.status is not EvaluationStatus.ERRORED and self.error_code is not None:
            raise ValueError("error_code is only valid for errored evaluations")
        return self
