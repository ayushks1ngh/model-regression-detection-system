"""Deterministic JSON report construction from evaluation evidence."""

from model_regression_detection import __version__
from model_regression_detection.execution.report import LocalEvaluationReport
from model_regression_detection.policy.models import CaseSummary
from model_regression_detection.reporting.models import (
    JsonReport,
    ReportCase,
    ReportEvaluation,
    ReportProvenance,
)
from model_regression_detection.specification.models import EvaluationSpecification

_MAX_OUTPUT_EXCERPT = 1_000


def _output_excerpt(output: str | None) -> str | None:
    """Bound provider output for the report without altering the stored outcome."""
    if output is None:
        return None
    if len(output) <= _MAX_OUTPUT_EXCERPT:
        return output
    return f"{output[:_MAX_OUTPUT_EXCERPT]}…"


def build_json_report(
    specification: EvaluationSpecification,
    report: LocalEvaluationReport,
) -> JsonReport:
    """Build a deterministic, bounded, versioned report from immutable evidence."""
    summaries: dict[str, CaseSummary] = {case.case_key: case for case in report.gate.cases}
    provenance = ReportProvenance(
        suite=specification.suite,
        configuration_hash=report.run.configuration_hash,
        dataset_hash=report.run.dataset_hash,
        prompt=specification.prompt.target,
        model=specification.model.target,
        agent=specification.agent.target if specification.agent is not None else None,
    )
    cases = tuple(
        ReportCase(
            case_key=result.case_key,
            ordinal=result.ordinal,
            critical=summaries[result.case_key].critical,
            outcome=summaries[result.case_key].outcome,
            provider_status=result.provider_result.status,
            resolved_model=result.provider_result.resolved_model,
            latency_ms=result.provider_result.latency_ms,
            output_excerpt=_output_excerpt(result.provider_result.output),
            provider_error=result.provider_result.error,
            evaluations=tuple(
                ReportEvaluation(
                    evaluator_name=evaluation.evaluator_name,
                    evaluator_type=evaluation.evaluator_type,
                    status=evaluation.status,
                    explanation=evaluation.explanation,
                    error_code=evaluation.error_code,
                )
                for evaluation in result.evaluations
            ),
        )
        for result in report.run.cases
    )
    return JsonReport(
        generator_version=__version__,
        gate_outcome=report.gate.outcome,
        provenance=provenance,
        metrics=report.gate.metrics,
        rules=report.gate.rules,
        cases=cases,
        metadata=dict(specification.metadata),
    )
