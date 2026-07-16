"""Tests for per-run execution limits."""

from copy import deepcopy
from typing import Any

import pytest

from model_regression_detection.execution.limits import (
    LimitExceededError,
    effective_output_tokens,
)
from model_regression_detection.execution.models import LocalRunResult
from model_regression_detection.execution.runner import execute_local
from model_regression_detection.providers import ErrorCategory, FakeProvider, FakeResponse
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


def document_with_limits(**limits: object) -> dict[str, Any]:
    """Return a single-case document with the given execution limits."""
    document = valid_document()
    document["limits"] = limits
    return document


async def run(document: dict[str, Any], responses: dict[str, FakeResponse]) -> LocalRunResult:
    """Execute a specification locally."""
    specification = EvaluationSpecificationV1.model_validate(document)
    return await execute_local(specification, FakeProvider(responses))


@pytest.mark.anyio
async def test_max_cases_preflight_rejects_before_calls() -> None:
    document = document_with_limits(max_cases=1)
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    document["cases"].append(second)

    with pytest.raises(LimitExceededError) as exc_info:
        await run(document, {"refund": FakeResponse(output="30 days")})

    assert exc_info.value.code == "max_cases_exceeded"


@pytest.mark.anyio
async def test_estimated_cost_preflight_rejection() -> None:
    document = document_with_limits(max_estimated_cost=0.01, estimated_cost_per_case=0.05)

    with pytest.raises(LimitExceededError) as exc_info:
        await run(document, {"refund": FakeResponse(output="30 days")})

    assert exc_info.value.code == "max_estimated_cost_exceeded"


def test_effective_output_tokens_uses_tighter_limit() -> None:
    document = document_with_limits(max_output_tokens=32)
    document["model"]["max_output_tokens"] = 256
    specification = EvaluationSpecificationV1.model_validate(document)

    assert effective_output_tokens(specification) == 32


def test_effective_output_tokens_defaults_to_model() -> None:
    specification = EvaluationSpecificationV1.model_validate(valid_document())

    assert effective_output_tokens(specification) == specification.model.max_output_tokens


@pytest.mark.anyio
async def test_total_cost_cap_stops_new_calls() -> None:
    document = document_with_limits(max_total_cost=0.10)
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    document["cases"].append(second)

    result = await run(
        document,
        {
            "refund": FakeResponse(output="30 days", cost=0.10),
            "second": FakeResponse(output="should not be called", cost=0.10),
        },
    )

    assert result.cases[0].provider_result.status == "success"
    assert result.cases[1].provider_result.status == "error"
    assert result.cases[1].provider_result.error is not None
    assert result.cases[1].provider_result.error.category is ErrorCategory.BUDGET_EXCEEDED


@pytest.mark.anyio
async def test_within_limits_runs_normally() -> None:
    document = document_with_limits(max_cases=5, max_total_cost=1.0)

    result = await run(document, {"refund": FakeResponse(output="30 days", cost=0.01)})

    assert result.total_cases == 1
    assert result.successful_cases == 1
