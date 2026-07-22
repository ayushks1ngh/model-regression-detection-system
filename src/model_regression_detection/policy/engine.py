"""Pure aggregation and fixed-policy decision engine."""

from typing import Literal

from model_regression_detection.evaluators import EvaluationStatus
from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.policy.models import (
    BaselineComparison,
    CaseOutcome,
    CaseSummary,
    GateDecision,
    GateOutcome,
    RuleDecision,
    RuleStatus,
    RunMetrics,
)
from model_regression_detection.specification.models import EvaluationSpecification


def _case_summaries(
    specification: EvaluationSpecification,
    run: LocalRunResult,
) -> tuple[CaseSummary, ...]:
    """Derive required-evaluator case outcomes in specification order."""
    case_definitions = {case.key: case for case in specification.cases}
    evaluator_required = {
        evaluator.name: evaluator.required for evaluator in specification.evaluators
    }
    summaries: list[CaseSummary] = []
    for result in run.cases:
        statuses = [evaluation.status for evaluation in result.evaluations]
        required_statuses = [
            evaluation.status
            for evaluation in result.evaluations
            if evaluator_required[evaluation.evaluator_name]
        ]
        if result.provider_result.status == "error" or any(
            status in {EvaluationStatus.ERRORED, EvaluationStatus.NOT_APPLICABLE}
            for status in required_statuses
        ):
            outcome = CaseOutcome.ERROR
        elif any(status is EvaluationStatus.FAILED for status in required_statuses):
            outcome = CaseOutcome.FAILED
        else:
            outcome = CaseOutcome.PASSED
        definition = case_definitions[result.case_key]
        summaries.append(
            CaseSummary(
                case_key=result.case_key,
                critical=definition.critical,
                outcome=outcome,
                passed_evaluators=statuses.count(EvaluationStatus.PASSED),
                failed_evaluators=statuses.count(EvaluationStatus.FAILED),
                errored_evaluators=statuses.count(EvaluationStatus.ERRORED),
                not_applicable_evaluators=statuses.count(EvaluationStatus.NOT_APPLICABLE),
            )
        )
    return tuple(summaries)


def _metrics(run: LocalRunResult, cases: tuple[CaseSummary, ...]) -> RunMetrics:
    """Aggregate case outcomes, provider latency, and known token usage."""
    passed = sum(case.outcome is CaseOutcome.PASSED for case in cases)
    failed = sum(case.outcome is CaseOutcome.FAILED for case in cases)
    errors = sum(case.outcome is CaseOutcome.ERROR for case in cases)
    input_tokens = 0
    output_tokens = 0
    unknown_usage = 0
    for result in run.cases:
        usage = result.provider_result.usage
        if usage is None:
            unknown_usage += 1
        else:
            input_tokens += usage.input_tokens
            output_tokens += usage.output_tokens
    return RunMetrics(
        total_cases=len(cases),
        passed_cases=passed,
        failed_cases=failed,
        error_cases=errors,
        pass_rate=passed / len(cases),
        error_rate=errors / len(cases),
        critical_failed_cases=tuple(
            case.case_key for case in cases if case.critical and case.outcome is CaseOutcome.FAILED
        ),
        critical_error_cases=tuple(
            case.case_key for case in cases if case.critical and case.outcome is CaseOutcome.ERROR
        ),
        total_latency_ms=sum(result.provider_result.latency_ms for result in run.cases),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cases_with_unknown_usage=unknown_usage,
    )


def _rules(
    specification: EvaluationSpecification,
    metrics: RunMetrics,
    cases: tuple[CaseSummary, ...],
    baseline: BaselineComparison | None = None,
) -> tuple[RuleDecision, ...]:
    """Evaluate fixed rules in stable precedence order.

    When *baseline* is provided the three baseline-drop rules are
    evaluated against observed deltas; otherwise they report
    NOT_APPLICABLE.
    """
    policy = specification.policy
    decisions: list[RuleDecision] = []

    error_ok = metrics.error_rate <= policy.maximum_error_rate
    decisions.append(
        RuleDecision(
            rule_id="maximum_error_rate",
            status=RuleStatus.PASSED if error_ok else RuleStatus.INSUFFICIENT_EVIDENCE,
            observed=metrics.error_rate,
            threshold=policy.maximum_error_rate,
            unit="ratio",
            explanation=(
                "Execution error rate is within the allowed maximum"
                if error_ok
                else "Execution error rate exceeds the allowed maximum"
            ),
            affected_cases=tuple(
                case.case_key for case in cases if case.outcome is CaseOutcome.ERROR
            ),
        )
    )

    no_critical_errors = not metrics.critical_error_cases
    decisions.append(
        RuleDecision(
            rule_id="critical_case_evidence",
            status=(RuleStatus.PASSED if no_critical_errors else RuleStatus.INSUFFICIENT_EVIDENCE),
            observed=len(metrics.critical_error_cases),
            threshold=0,
            unit="count",
            explanation=(
                "All critical cases produced valid evidence"
                if no_critical_errors
                else "Critical cases are missing valid evidence"
            ),
            affected_cases=metrics.critical_error_cases,
        )
    )

    pass_rate_ok = metrics.pass_rate >= policy.minimum_pass_rate
    decisions.append(
        RuleDecision(
            rule_id="minimum_pass_rate",
            status=RuleStatus.PASSED if pass_rate_ok else RuleStatus.VIOLATED,
            observed=metrics.pass_rate,
            threshold=policy.minimum_pass_rate,
            unit="ratio",
            explanation=(
                "Case pass rate meets the minimum"
                if pass_rate_ok
                else "Case pass rate is below the minimum"
            ),
        )
    )

    critical_quality_ok = not metrics.critical_failed_cases
    decisions.append(
        RuleDecision(
            rule_id="critical_cases_must_pass",
            status=(
                RuleStatus.PASSED
                if not policy.critical_cases_must_pass or critical_quality_ok
                else RuleStatus.VIOLATED
            ),
            observed=critical_quality_ok,
            threshold=policy.critical_cases_must_pass,
            unit="boolean",
            explanation=(
                "Critical-case quality requirement is satisfied"
                if not policy.critical_cases_must_pass or critical_quality_ok
                else "One or more critical cases failed required evaluators"
            ),
            affected_cases=metrics.critical_failed_cases,
        )
    )

    decisions.extend(_baseline_drop_rules(specification, baseline))
    return tuple(decisions)


def _baseline_drop_rules(
    specification: EvaluationSpecification,
    baseline: BaselineComparison | None,
) -> list[RuleDecision]:
    """Evaluate the three baseline-drop rules or mark them NOT_APPLICABLE."""
    policy = specification.policy

    if baseline is None:
        return [
            RuleDecision(
                rule_id="maximum_pass_rate_drop",
                status=RuleStatus.NOT_APPLICABLE,
                observed=None,
                threshold=policy.maximum_pass_rate_drop,
                unit="ratio",
                explanation="Baseline comparison is not available in local policy evaluation",
            ),
            RuleDecision(
                rule_id="maximum_latency_increase_percent",
                status=RuleStatus.NOT_APPLICABLE,
                observed=None,
                threshold=policy.maximum_latency_increase_percent,
                unit="percent",
                explanation="Baseline comparison is not available in local policy evaluation",
            ),
            RuleDecision(
                rule_id="maximum_cost_increase_percent",
                status=RuleStatus.NOT_APPLICABLE,
                observed=None,
                threshold=policy.maximum_cost_increase_percent,
                unit="percent",
                explanation="Cost and baseline comparison are not available in M5",
            ),
        ]

    affected = baseline.missing_in_candidate + baseline.missing_in_baseline

    if not baseline.configuration_match or not baseline.dataset_match:
        incompatible_msg = _incompatible_reason(baseline)
        return [
            RuleDecision(
                rule_id="maximum_pass_rate_drop",
                status=RuleStatus.INSUFFICIENT_EVIDENCE,
                observed=baseline.pass_rate_drop,
                threshold=policy.maximum_pass_rate_drop,
                unit="ratio",
                explanation=incompatible_msg,
                affected_cases=affected,
            ),
            RuleDecision(
                rule_id="maximum_latency_increase_percent",
                status=RuleStatus.INSUFFICIENT_EVIDENCE,
                observed=baseline.latency_increase_pct,
                threshold=policy.maximum_latency_increase_percent,
                unit="percent",
                explanation=incompatible_msg,
                affected_cases=affected,
            ),
            RuleDecision(
                rule_id="maximum_cost_increase_percent",
                status=RuleStatus.INSUFFICIENT_EVIDENCE,
                observed=baseline.cost_increase_pct,
                threshold=policy.maximum_cost_increase_percent,
                unit="percent",
                explanation=incompatible_msg,
                affected_cases=affected,
            ),
        ]

    def _eval_drop_rule(
        rule_id: str,
        threshold: float | None,
        observed: float | None,
        unit: Literal["ratio", "percent"],
        passed_text: str,
        failed_text: str,
        no_obs_text: str,
        no_thresh_text: str,
    ) -> RuleDecision:
        if threshold is None:
            return RuleDecision(
                rule_id=rule_id,
                status=RuleStatus.NOT_APPLICABLE,
                observed=observed,
                threshold=None,
                unit=unit,
                explanation=no_thresh_text,
            )
        if observed is None:
            return RuleDecision(
                rule_id=rule_id,
                status=RuleStatus.INSUFFICIENT_EVIDENCE,
                observed=None,
                threshold=threshold,
                unit=unit,
                explanation=no_obs_text,
            )
        ok = observed <= threshold
        return RuleDecision(
            rule_id=rule_id,
            status=RuleStatus.PASSED if ok else RuleStatus.VIOLATED,
            observed=observed,
            threshold=threshold,
            unit=unit,
            explanation=passed_text if ok else failed_text,
        )

    return [
        _eval_drop_rule(
            rule_id="maximum_pass_rate_drop",
            threshold=policy.maximum_pass_rate_drop,
            observed=baseline.pass_rate_drop,
            unit="ratio",
            passed_text="Pass rate drop is within the allowed maximum",
            failed_text="Pass rate drop exceeds the allowed maximum",
            no_obs_text="Pass rate drop cannot be computed",
            no_thresh_text="No maximum_pass_rate_drop policy configured",
        ),
        _eval_drop_rule(
            rule_id="maximum_latency_increase_percent",
            threshold=policy.maximum_latency_increase_percent,
            observed=baseline.latency_increase_pct,
            unit="percent",
            passed_text="Latency increase is within the allowed maximum",
            failed_text="Latency increase exceeds the allowed maximum",
            no_obs_text="Latency increase cannot be computed",
            no_thresh_text="No maximum_latency_increase_percent policy configured",
        ),
        _eval_drop_rule(
            rule_id="maximum_cost_increase_percent",
            threshold=policy.maximum_cost_increase_percent,
            observed=baseline.cost_increase_pct,
            unit="percent",
            passed_text="Cost increase is within the allowed maximum",
            failed_text="Cost increase exceeds the allowed maximum",
            no_obs_text="Cost increase cannot be computed",
            no_thresh_text="No maximum_cost_increase_percent policy configured",
        ),
    ]


def _incompatible_reason(baseline: BaselineComparison) -> str:
    """Build a human-readable incompatibility explanation."""
    reasons: list[str] = []
    if not baseline.configuration_match:
        reasons.append("configuration hash mismatch between baseline and candidate")
    if not baseline.dataset_match:
        reasons.append("dataset hash mismatch between baseline and candidate")
    if baseline.missing_in_candidate:
        reasons.append(
            f"cases present in baseline but missing in candidate: {baseline.missing_in_candidate}"
        )
    if baseline.missing_in_baseline:
        reasons.append(
            f"cases present in candidate but missing in baseline: {baseline.missing_in_baseline}"
        )
    return "Baseline comparison unavailable: " + "; ".join(reasons)


def aggregate_and_decide(
    specification: EvaluationSpecification,
    run: LocalRunResult,
) -> GateDecision:
    """Aggregate one completed local run and produce a deterministic gate decision."""
    cases = _case_summaries(specification, run)
    metrics = _metrics(run, cases)
    rules = _rules(specification, metrics, cases)
    statuses = {rule.status for rule in rules}
    if RuleStatus.INSUFFICIENT_EVIDENCE in statuses:
        outcome = GateOutcome.ERROR
    elif RuleStatus.VIOLATED in statuses:
        outcome = GateOutcome.FAIL
    else:
        outcome = GateOutcome.PASS
    return GateDecision(outcome=outcome, metrics=metrics, cases=cases, rules=rules)


def compare_and_decide(
    specification: EvaluationSpecification,
    candidate_run: LocalRunResult,
    baseline_run: LocalRunResult,
) -> GateDecision:
    """Gate decision that includes baseline-drop rule evaluation."""
    from model_regression_detection.policy.comparison import (
        compare_candidate_to_baseline,
    )

    baseline = compare_candidate_to_baseline(candidate_run, baseline_run, specification)
    cases = _case_summaries(specification, candidate_run)
    metrics = _metrics(candidate_run, cases)
    rules = _rules(specification, metrics, cases, baseline=baseline)
    statuses = {rule.status for rule in rules}
    if RuleStatus.INSUFFICIENT_EVIDENCE in statuses:
        outcome = GateOutcome.ERROR
    elif RuleStatus.VIOLATED in statuses:
        outcome = GateOutcome.FAIL
    else:
        outcome = GateOutcome.PASS
    return GateDecision(outcome=outcome, metrics=metrics, cases=cases, rules=rules)
