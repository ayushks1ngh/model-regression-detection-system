"""Immutable evidence models produced by local execution."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from model_regression_detection.evaluators import EvaluationResult
from model_regression_detection.providers.contracts import InferenceResult


class ExecutionModel(BaseModel):
    """Strict immutable base for local execution evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CaseExecutionResult(ExecutionModel):
    """Terminal provider and evaluator evidence for one golden case."""

    case_key: str
    ordinal: Annotated[int, Field(ge=0)]
    request_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    provider_result: InferenceResult
    evaluations: tuple[EvaluationResult, ...]


class LocalRunResult(ExecutionModel):
    """Complete sequential local execution evidence in deterministic case order."""

    status: Literal["completed", "cancelled"]
    suite: str
    configuration_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    dataset_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    total_cases: Annotated[int, Field(ge=0)]
    successful_cases: Annotated[int, Field(ge=0)]
    error_cases: Annotated[int, Field(ge=0)]
    cases: tuple[CaseExecutionResult, ...]
