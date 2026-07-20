"""Tests for deterministic sequential local execution."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from model_regression_detection.execution import execute_local
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    ProviderError,
)
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


def specification(document: dict[str, Any] | None = None) -> EvaluationSpecificationV1:
    """Validate a runner specification fixture."""
    return EvaluationSpecificationV1.model_validate(document or valid_document())


@pytest.mark.anyio
async def test_executes_each_case_once_in_specification_order() -> None:
    document = valid_document()
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    second["inputs"] = {"request": "Second request"}
    document["cases"].append(second)
    provider = FakeProvider(
        {
            "refund": FakeResponse(output="First", input_tokens=1, output_tokens=1),
            "second": FakeResponse(output="Second", input_tokens=2, output_tokens=1),
        }
    )

    result = await execute_local(specification(document), provider)

    assert result.status == "completed"
    assert result.total_cases == 2
    assert result.successful_cases == 2
    assert result.error_cases == 0
    assert [case.case_key for case in result.cases] == ["refund", "second"]
    assert [case.ordinal for case in result.cases] == [0, 1]
    assert all(case.evaluations[0].status.value == "failed" for case in result.cases)


@pytest.mark.anyio
async def test_partial_provider_failure_is_accounted_not_reclassified() -> None:
    document = valid_document()
    second = deepcopy(document["cases"][0])
    second["key"] = "second"
    document["cases"].append(second)
    provider = FakeProvider(
        {
            "refund": FakeResponse(output="success"),
            "second": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.TIMEOUT,
                    code="timeout",
                    message="timed out",
                    retryable=True,
                )
            ),
        }
    )

    result = await execute_local(specification(document), provider)

    assert result.successful_cases == 1
    assert result.error_cases == 1
    assert result.cases[1].provider_result.error is not None
    assert result.cases[1].provider_result.error.category is ErrorCategory.TIMEOUT


@pytest.mark.anyio
async def test_repeated_runs_produce_identical_result() -> None:
    provider = FakeProvider({"refund": FakeResponse(output="30 days", latency_ms=1.0)})
    spec = specification()

    first = await execute_local(spec, provider)
    second = await execute_local(spec, provider)

    assert first == second


@pytest.mark.anyio
async def test_non_string_inputs_render_as_canonical_json() -> None:
    document = valid_document()
    document["prompt"]["variables"] = ["request", "context"]
    document["prompt"]["messages"][0]["content"] = "{request} context={context}"
    document["cases"][0]["inputs"]["context"] = {"b": 2, "a": 1}

    result = await execute_local(
        specification(document),
        FakeProvider({"refund": FakeResponse(output="ok")}),
    )

    assert len(result.cases[0].request_hash) == 64


@pytest.mark.anyio
async def test_unsafe_template_expression_produces_errored_case() -> None:
    document = valid_document()
    document["prompt"]["messages"][0]["content"] = "{request.__class__}"

    result = await execute_local(
        specification(document),
        FakeProvider({"refund": FakeResponse(output="should not execute")}),
    )

    assert result.status == "completed"
    assert result.successful_cases == 0
    assert result.error_cases == 1
    assert result.cases[0].provider_result.error is not None
    assert "template_render_error" in result.cases[0].provider_result.error.code


def test_fake_fixture_example_is_valid() -> None:
    path = Path(__file__).parents[1] / "examples" / "fake-responses.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload["responses"]) == {"refund-policy", "greeting"}


def test_fake_fixture_with_cost(tmp_path: Path) -> None:
    from model_regression_detection.providers.fixtures import load_fake_responses

    fixture = tmp_path / "with_cost.json"
    fixture.write_text(
        '{"responses":{"test":{"output":"ok","cost":0.05,"input_tokens":10,"output_tokens":5,"latency_ms":1.0}}}',
        encoding="utf-8",
    )
    responses = load_fake_responses(fixture)

    assert responses["test"].cost == 0.05
    assert responses["test"].output == "ok"
