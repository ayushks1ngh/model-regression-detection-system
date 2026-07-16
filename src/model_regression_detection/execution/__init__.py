"""Sequential execution and local fixed-policy composition."""

from model_regression_detection.execution.limits import LimitExceededError
from model_regression_detection.execution.models import CaseExecutionResult, LocalRunResult
from model_regression_detection.execution.report import (
    LocalEvaluationReport,
    execute_local_evaluation,
)
from model_regression_detection.execution.runner import execute_local

__all__ = [
    "CaseExecutionResult",
    "LimitExceededError",
    "LocalEvaluationReport",
    "LocalRunResult",
    "execute_local",
    "execute_local_evaluation",
]
