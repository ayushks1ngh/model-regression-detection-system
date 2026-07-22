"""Baseline-vs-candidate comparison engine."""

from model_regression_detection.evaluators import EvaluationStatus
from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.policy.models import (
    BaselineComparison,
    CaseOutcome,
)
from model_regression_detection.specification.models import EvaluationSpecification


def _case_outcome(
    run: LocalRunResult,
    case_key: str,
    specification: EvaluationSpecification,
) -> CaseOutcome | None:
    """Derive case outcome for a single case in a run (or None if not found)."""
    evaluator_required = {e.name: e.required for e in specification.evaluators}
    for result in run.cases:
        if result.case_key != case_key:
            continue
        required_statuses = [
            e.status for e in result.evaluations if evaluator_required[e.evaluator_name]
        ]
        if result.provider_result.status == "error" or any(
            s in {EvaluationStatus.ERRORED, EvaluationStatus.NOT_APPLICABLE}
            for s in required_statuses
        ):
            return CaseOutcome.ERROR
        if any(s is EvaluationStatus.FAILED for s in required_statuses):
            return CaseOutcome.FAILED
        return CaseOutcome.PASSED
    return None


def _pass_rate(
    run: LocalRunResult,
    specification: EvaluationSpecification,
) -> float | None:
    """Compute pass rate for a run, or None if no cases."""
    if not run.cases:
        return None
    outcomes = [_case_outcome(run, result.case_key, specification) for result in run.cases]
    outcomes = [o for o in outcomes if o is not None]
    if not outcomes:
        return None
    passed = sum(1 for o in outcomes if o is CaseOutcome.PASSED)
    return passed / len(outcomes)


def _aggregate_latency(run: LocalRunResult) -> float:
    """Total latency in ms across all case results."""
    return sum(result.provider_result.latency_ms for result in run.cases)


def _aggregate_cost(run: LocalRunResult) -> float | None:
    """Total cost across all case results, or None if any case has no cost."""
    total: float = 0.0
    for result in run.cases:
        cost = result.provider_result.cost
        if cost is None:
            return None
        total += cost
    return total


def _pct_change(baseline: float, candidate: float) -> float:
    """Compute percentage change from baseline to candidate.

    Returns 0.0 if baseline is 0 (no change from zero).
    """
    if baseline == 0.0:
        return 0.0
    return (candidate - baseline) / baseline * 100.0


def compare_candidate_to_baseline(
    candidate_run: LocalRunResult,
    baseline_run: LocalRunResult,
    specification: EvaluationSpecification,
) -> BaselineComparison:
    """Compare a candidate run against a baseline run and produce deltas.

    Pairing is done on stable case keys. Missing keys in either direction
    are explicitly reported. Compatibility (suite, configuration, dataset)
    is checked and surfaced but does not block comparison — mismatches
    simply cause the corresponding drop rules to be flagged.
    """
    candidate_keys = {r.case_key for r in candidate_run.cases}
    baseline_keys = {r.case_key for r in baseline_run.cases}
    matching = tuple(sorted(candidate_keys & baseline_keys))
    missing_in_candidate = tuple(sorted(baseline_keys - candidate_keys))
    missing_in_baseline = tuple(sorted(candidate_keys - baseline_keys))

    pass_rate_baseline = _pass_rate(baseline_run, specification)
    pass_rate_candidate = _pass_rate(candidate_run, specification)
    pass_rate_drop: float | None = None
    if pass_rate_baseline is not None and pass_rate_candidate is not None:
        drop = pass_rate_baseline - pass_rate_candidate
        pass_rate_drop = max(drop, 0.0)

    latency_ms_baseline = _aggregate_latency(baseline_run)
    latency_ms_candidate = _aggregate_latency(candidate_run)
    latency_increase_pct = max(_pct_change(latency_ms_baseline, latency_ms_candidate), 0.0)

    cost_baseline = _aggregate_cost(baseline_run)
    cost_candidate = _aggregate_cost(candidate_run)
    cost_increase_pct: float | None = None
    if cost_baseline is not None and cost_candidate is not None:
        cost_increase_pct = max(_pct_change(cost_baseline, cost_candidate), 0.0)

    return BaselineComparison(
        configuration_match=(candidate_run.configuration_hash == baseline_run.configuration_hash),
        dataset_match=(candidate_run.dataset_hash == baseline_run.dataset_hash),
        total_cases_candidate=len(candidate_run.cases),
        total_cases_baseline=len(baseline_run.cases),
        matching_case_keys=matching,
        missing_in_candidate=missing_in_candidate,
        missing_in_baseline=missing_in_baseline,
        pass_rate_baseline=pass_rate_baseline,
        pass_rate_candidate=pass_rate_candidate,
        pass_rate_drop=pass_rate_drop,
        latency_ms_baseline=latency_ms_baseline,
        latency_ms_candidate=latency_ms_candidate,
        latency_increase_pct=latency_increase_pct,
        cost_baseline=cost_baseline,
        cost_candidate=cost_candidate,
        cost_increase_pct=cost_increase_pct,
    )
