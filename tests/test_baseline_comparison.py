"""Tests for baseline comparison and baseline-drop rules (M15)."""

from copy import deepcopy
from typing import Any

import pytest

from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.execution.runner import execute_local
from model_regression_detection.policy import (
    GateOutcome,
    RuleStatus,
    aggregate_and_decide,
    compare_and_decide,
)
from model_regression_detection.policy.comparison import compare_candidate_to_baseline
from model_regression_detection.providers import FakeProvider, FakeResponse
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


def two_case_document() -> dict[str, Any]:
    """Return a two-case single-evaluator document with baseline policy."""
    document = valid_document()
    document["policy"] = {
        "minimum_pass_rate": 1.0,
        "maximum_pass_rate_drop": 0.0,
        "maximum_error_rate": 0.0,
        "critical_cases_must_pass": True,
        "maximum_latency_increase_percent": 0.0,
    }
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    second["critical"] = False
    document["cases"].append(second)
    return document


async def run_with_responses(
    document: dict[str, Any], responses: dict[str, FakeResponse]
) -> LocalRunResult:
    """Execute locally and return the raw run result."""
    specification = EvaluationSpecificationV1.model_validate(document)
    return await execute_local(specification, FakeProvider(responses))


# -- compare_candidate_to_baseline unit tests --


@pytest.mark.anyio
async def test_identical_runs_have_no_drop() -> None:
    document = two_case_document()
    responses = {
        "refund": FakeResponse(output="30 days", latency_ms=10.0, cost=0.01),
        "second": FakeResponse(output="30 days", latency_ms=5.0, cost=0.005),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, responses)
    candidate = await run_with_responses(document, responses)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.configuration_match is True
    assert comp.dataset_match is True
    assert comp.matching_case_keys == ("refund", "second")
    assert comp.missing_in_candidate == ()
    assert comp.missing_in_baseline == ()
    assert comp.pass_rate_drop == 0.0
    assert comp.latency_increase_pct == 0.0
    assert comp.cost_increase_pct == 0.0


@pytest.mark.anyio
async def test_pass_rate_drop_is_captured() -> None:
    document = two_case_document()
    baseline_responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    candidate_responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="wrong answer"),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, baseline_responses)
    candidate = await run_with_responses(document, candidate_responses)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.pass_rate_drop is not None
    assert comp.pass_rate_drop == pytest.approx(0.5)
    assert comp.pass_rate_baseline == 1.0
    assert comp.pass_rate_candidate == 0.5


@pytest.mark.anyio
async def test_configuration_mismatch_detected() -> None:
    document1 = two_case_document()
    document2 = deepcopy(document1)
    document2["prompt"]["messages"] = [{"role": "user", "content": "Different: {request}"}]

    responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    specification = EvaluationSpecificationV1.model_validate(document1)
    baseline = await run_with_responses(document1, responses)
    candidate = await run_with_responses(document2, responses)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.configuration_match is False


@pytest.mark.anyio
async def test_missing_cases_are_reported() -> None:
    document = two_case_document()
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(
        document,
        {
            "refund": FakeResponse(output="30 days"),
            "second": FakeResponse(output="30 days"),
        },
    )
    single = deepcopy(document)
    single["cases"] = [single["cases"][0]]
    candidate = await run_with_responses(
        single,
        {"refund": FakeResponse(output="30 days")},
    )

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.missing_in_candidate == ("second",)
    assert comp.missing_in_baseline == ()


@pytest.mark.anyio
async def test_latency_increase_is_captured() -> None:
    document = two_case_document()
    responses_baseline = {
        "refund": FakeResponse(output="30 days", latency_ms=10.0),
        "second": FakeResponse(output="30 days", latency_ms=5.0),
    }
    responses_candidate = {
        "refund": FakeResponse(output="30 days", latency_ms=20.0),
        "second": FakeResponse(output="30 days", latency_ms=15.0),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, responses_baseline)
    candidate = await run_with_responses(document, responses_candidate)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.latency_increase_pct == pytest.approx(133.33, rel=0.01)


@pytest.mark.anyio
async def test_cost_increase_is_captured() -> None:
    document = two_case_document()
    responses_baseline = {
        "refund": FakeResponse(output="30 days", cost=0.01),
        "second": FakeResponse(output="30 days", cost=0.01),
    }
    responses_candidate = {
        "refund": FakeResponse(output="30 days", cost=0.03),
        "second": FakeResponse(output="30 days", cost=0.03),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, responses_baseline)
    candidate = await run_with_responses(document, responses_candidate)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.cost_increase_pct is not None
    assert comp.cost_increase_pct == pytest.approx(200.0)


@pytest.mark.anyio
async def test_cost_is_none_when_baseline_missing_cost() -> None:
    document = two_case_document()
    responses_baseline = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    responses_candidate = {
        "refund": FakeResponse(output="30 days", cost=0.01),
        "second": FakeResponse(output="30 days", cost=0.01),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, responses_baseline)
    candidate = await run_with_responses(document, responses_candidate)

    comp = compare_candidate_to_baseline(candidate, baseline, specification)

    assert comp.cost_increase_pct is None
    assert comp.cost_baseline is None
    assert comp.cost_candidate is not None


# -- compare_and_decide integration tests --


@pytest.mark.anyio
async def test_no_regression_with_baseline_produces_pass() -> None:
    document = two_case_document()
    responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, responses)

    decision = compare_and_decide(specification, baseline, baseline)

    assert decision.outcome is GateOutcome.PASS
    baseline_rules = {
        r.rule_id: r.status
        for r in decision.rules
        if r.rule_id in {"maximum_pass_rate_drop", "maximum_latency_increase_percent"}
    }
    assert all(s is RuleStatus.PASSED for s in baseline_rules.values())


@pytest.mark.anyio
async def test_pass_rate_drop_violation_causes_fail() -> None:
    document = two_case_document()
    baseline_responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    candidate_responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="wrong answer"),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, baseline_responses)
    candidate = await run_with_responses(document, candidate_responses)

    decision = compare_and_decide(specification, candidate, baseline)

    assert decision.outcome is GateOutcome.FAIL
    drop_rule = next(r for r in decision.rules if r.rule_id == "maximum_pass_rate_drop")
    assert drop_rule.status is RuleStatus.VIOLATED
    assert drop_rule.observed == 0.5


@pytest.mark.anyio
async def test_latency_increase_violation_causes_fail() -> None:
    document = two_case_document()
    baseline_responses = {
        "refund": FakeResponse(output="30 days", latency_ms=10.0),
        "second": FakeResponse(output="30 days", latency_ms=5.0),
    }
    candidate_responses = {
        "refund": FakeResponse(output="30 days", latency_ms=100.0),
        "second": FakeResponse(output="30 days", latency_ms=50.0),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, baseline_responses)
    candidate = await run_with_responses(document, candidate_responses)

    decision = compare_and_decide(specification, candidate, baseline)

    assert decision.outcome is GateOutcome.FAIL
    latency_rule = next(
        r for r in decision.rules if r.rule_id == "maximum_latency_increase_percent"
    )
    assert latency_rule.status is RuleStatus.VIOLATED


@pytest.mark.anyio
async def test_cost_increase_violation_causes_fail() -> None:
    document = two_case_document()
    document["policy"]["maximum_cost_increase_percent"] = 0.0
    baseline_responses = {
        "refund": FakeResponse(output="30 days", cost=0.01),
        "second": FakeResponse(output="30 days", cost=0.01),
    }
    candidate_responses = {
        "refund": FakeResponse(output="30 days", cost=0.10),
        "second": FakeResponse(output="30 days", cost=0.10),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    baseline = await run_with_responses(document, baseline_responses)
    candidate = await run_with_responses(document, candidate_responses)

    decision = compare_and_decide(specification, candidate, baseline)

    assert decision.outcome is GateOutcome.FAIL
    cost_rule = next(r for r in decision.rules if r.rule_id == "maximum_cost_increase_percent")
    assert cost_rule.status is RuleStatus.VIOLATED


@pytest.mark.anyio
async def test_incompatible_baseline_produces_error_gate() -> None:
    document1 = two_case_document()
    document2 = deepcopy(document1)
    document2["prompt"]["messages"] = [{"role": "user", "content": "Different: {request}"}]

    responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    specification = EvaluationSpecificationV1.model_validate(document1)
    baseline = await run_with_responses(document1, responses)
    candidate = await run_with_responses(document2, responses)

    decision = compare_and_decide(specification, candidate, baseline)

    baseline_rules = {
        r.rule_id: r.status
        for r in decision.rules
        if r.rule_id
        in {
            "maximum_pass_rate_drop",
            "maximum_latency_increase_percent",
            "maximum_cost_increase_percent",
        }
    }
    assert all(s is RuleStatus.INSUFFICIENT_EVIDENCE for s in baseline_rules.values())
    assert decision.outcome is GateOutcome.ERROR


@pytest.mark.anyio
async def test_aggregate_and_decide_still_works_without_baseline() -> None:
    """Ensure existing non-baseline path still produces NOT_APPLICABLE."""
    document = two_case_document()
    responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }
    specification = EvaluationSpecificationV1.model_validate(document)
    run = await run_with_responses(document, responses)
    decision = aggregate_and_decide(specification, run)

    assert decision.outcome is GateOutcome.PASS
    baseline_rule_ids = {
        "maximum_pass_rate_drop",
        "maximum_latency_increase_percent",
        "maximum_cost_increase_percent",
    }
    baseline_rules = {
        rule.rule_id: rule.status for rule in decision.rules if rule.rule_id in baseline_rule_ids
    }
    assert set(baseline_rules.values()) == {RuleStatus.NOT_APPLICABLE}
