"""Deterministic built-in evaluator contracts and execution."""

from model_regression_detection.evaluators.builtin import evaluate_case
from model_regression_detection.evaluators.models import EvaluationResult, EvaluationStatus

__all__ = ["EvaluationResult", "EvaluationStatus", "evaluate_case"]
