"""Sequential local execution without evaluator or policy logic."""

from model_regression_detection.execution.runner import (
    CaseExecutionResult,
    LocalRunResult,
    execute_local,
)

__all__ = ["CaseExecutionResult", "LocalRunResult", "execute_local"]
