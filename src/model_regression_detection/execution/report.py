"""Composition of local execution evidence and a fixed gate decision."""

from pydantic import BaseModel, ConfigDict

from model_regression_detection.execution.cancellation import CancellationToken
from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.execution.runner import execute_local
from model_regression_detection.policy.engine import aggregate_and_decide
from model_regression_detection.policy.models import GateDecision
from model_regression_detection.providers.contracts import Provider
from model_regression_detection.specification.models import EvaluationSpecification


class LocalEvaluationReport(BaseModel):
    """Immutable envelope that keeps execution and gate evidence distinct."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run: LocalRunResult
    gate: GateDecision


async def execute_local_evaluation(
    specification: EvaluationSpecification,
    provider: Provider,
    cancellation_token: CancellationToken | None = None,
) -> LocalEvaluationReport:
    """Execute locally, then derive a pure deterministic fixed-policy decision."""
    run = await execute_local(specification, provider, cancellation_token)
    gate = aggregate_and_decide(specification, run)
    return LocalEvaluationReport(run=run, gate=gate)
