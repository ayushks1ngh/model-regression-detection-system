"""Tests for local aggregation and the fixed gate policy engine."""

from copy import deepcopy
from typing import Any

import pytest

from model_regression_detection.execution.runner import execute_local
from model_regression_detection.policy import (
    CaseOutcome,
    GateDecision,
    GateOutcome,
    RuleStatus,
    aggregate_and_decide,
)
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    ProviderError,
)
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


def two_case_document() -> dict[str, Any]:
    """Return a two-case single-evaluator document for policy scenarios."""
    document = valid_document()
    document["policy"] = {
        "minimum_pass_rate": 1.0,
        "maximum_pass_rate_drop": 0.0,
        "maximum_error_rate": 0.0,
        "critical_cases_must_pass": True,
    }
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    second["critical"] = False
    document["cases"].append(second)
    return document


async def decide(document: dict[str, Any], responses: dict[str, FakeResponse]) -> GateDecision:
    """Execute locally and return the fixed gate decision."""
    specification = EvaluationSpecificationV1.model_validate(document)
    run = await execute_local(specification, FakeProvider(responses))
    return aggregate_and_decide(specification, run)


@pytest.mark.anyio
async def test_all_pass_produces_pass_gate() -> None:
    decision = await decide(
        two_case_document(),
        {
            "refund": FakeResponse(output="30 days", input_tokens=3, output_tokens=2),
            "second": FakeResponse(output="30 days", input_tokens=1, output_tokens=1),
        },
    )

    assert decision.outcome is GateOutcome.PASS
    assert decision.metrics.pass_rate == 1.0
    assert decision.metrics.total_tokens == 7


@pytest.mark.anyio
async def test_quality_failure_produces_fail_gate() -> None:
    decision = await decide(
        two_case_document(),
        {
            "refund": FakeResponse(output="wrong answer"),
            "second": FakeResponse(output="30 days"),
        },
    )

    assert decision.outcome is GateOutcome.FAIL
    assert decision.cases[0].outcome is CaseOutcome.FAILED


@pytest.mark.anyio
async def test_provider_error_produces_error_gate_not_fail() -> None:
    decision = await decide(
        two_case_document(),
        {
            "refund": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.TIMEOUT,
                    code="timeout",
                    message="timed out",
                    retryable=True,
                )
            ),
            "second": FakeResponse(output="30 days"),
        },
    )

    assert decision.outcome is GateOutcome.ERROR
    assert decision.cases[0].outcome is CaseOutcome.ERROR
    assert "refund" in decision.metrics.critical_error_cases


@pytest.mark.anyio
async def test_optional_evaluator_failure_does_not_change_case_outcome() -> None:
    document = two_case_document()
    document["evaluators"] = [
        {"name": "answer-match", "type": "normalized_match", "required": True},
        {"name": "json-shape", "type": "json_valid", "required": False},
    ]
    for case in document["cases"]:
        case["evaluators"] = ["answer-match", "json-shape"]

    decision = await decide(
        document,
        {
            "refund": FakeResponse(output="30 days"),
            "second": FakeResponse(output="30 days"),
        },
    )

    assert decision.outcome is GateOutcome.PASS
    assert decision.cases[0].failed_evaluators == 1
    assert decision.cases[0].outcome is CaseOutcome.PASSED


@pytest.mark.anyio
async def test_minimum_pass_rate_threshold_is_boundary_inclusive() -> None:
    document = two_case_document()
    document["policy"]["minimum_pass_rate"] = 0.5
    document["policy"]["critical_cases_must_pass"] = False

    decision = await decide(
        document,
        {
            "refund": FakeResponse(output="30 days"),
            "second": FakeResponse(output="wrong"),
        },
    )

    assert decision.metrics.pass_rate == 0.5
    assert decision.outcome is GateOutcome.PASS


@pytest.mark.anyio
async def test_baseline_rules_are_not_applicable_locally() -> None:
    decision = await decide(
        two_case_document(),
        {
            "refund": FakeResponse(output="30 days"),
            "second": FakeResponse(output="30 days"),
        },
    )

    baseline_rule_ids = {
        "maximum_pass_rate_drop",
        "maximum_latency_increase_percent",
        "maximum_cost_increase_percent",
    }
    baseline_rules = {
        rule.rule_id: rule.status for rule in decision.rules if rule.rule_id in baseline_rule_ids
    }
    assert set(baseline_rules.values()) == {RuleStatus.NOT_APPLICABLE}


@pytest.mark.anyio
async def test_decision_is_deterministic() -> None:
    document = two_case_document()
    responses = {
        "refund": FakeResponse(output="30 days"),
        "second": FakeResponse(output="30 days"),
    }

    first = await decide(document, responses)
    second = await decide(deepcopy(document), responses)

    assert first == second


@pytest.mark.anyio
async def test_unknown_usage_is_counted_not_zeroed() -> None:
    decision = await decide(
        two_case_document(),
        {
            "refund": FakeResponse(output="30 days", input_tokens=2, output_tokens=1),
            "second": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.RATE_LIMITED,
                    code="rate",
                    message="slow down",
                    retryable=True,
                )
            ),
        },
    )

    assert decision.metrics.cases_with_unknown_usage == 1
    assert decision.metrics.total_tokens == 3
