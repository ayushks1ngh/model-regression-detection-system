"""Tests for the versioned local JSON report."""

import json
from copy import deepcopy
from typing import Any

import pytest

from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    ProviderError,
)
from model_regression_detection.reporting import build_json_report
from model_regression_detection.reporting.models import REPORT_SCHEMA_VERSION, JsonReport
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


async def report(document: dict[str, Any], responses: dict[str, FakeResponse]) -> JsonReport:
    """Execute locally and build a versioned JSON report."""
    specification = EvaluationSpecificationV1.model_validate(document)
    evaluation = await execute_local_evaluation(specification, FakeProvider(responses))
    return build_json_report(specification, evaluation)


@pytest.mark.anyio
async def test_report_includes_provenance_and_targets() -> None:
    result = await report(valid_document(), {"refund": FakeResponse(output="30 days")})

    assert result.schema_version == REPORT_SCHEMA_VERSION
    assert result.provenance.prompt.kind.value == "prompt"
    assert result.provenance.model.kind.value == "model"
    assert result.provenance.agent is not None
    assert len(result.provenance.configuration_hash) == 64


@pytest.mark.anyio
async def test_report_is_valid_json_and_deterministic() -> None:
    document = valid_document()
    responses = {"refund": FakeResponse(output="30 days")}

    first = await report(document, responses)
    second = await report(deepcopy(document), responses)
    payload = json.loads(first.model_dump_json())

    assert first == second
    assert payload["gate_outcome"] in {"pass", "fail", "error"}
    assert payload["cases"][0]["case_key"] == "refund"


@pytest.mark.anyio
async def test_report_preserves_case_order() -> None:
    document = valid_document()
    second = deepcopy(document["cases"][0])
    second["key"] = "aaa-late-key"
    document["cases"].append(second)

    result = await report(
        document,
        {
            "refund": FakeResponse(output="30 days"),
            "aaa-late-key": FakeResponse(output="30 days"),
        },
    )

    assert [case.case_key for case in result.cases] == ["refund", "aaa-late-key"]


@pytest.mark.anyio
async def test_report_truncates_large_output() -> None:
    result = await report(valid_document(), {"refund": FakeResponse(output="y" * 5_000)})

    excerpt = result.cases[0].output_excerpt
    assert excerpt is not None
    assert len(excerpt) == 1_001
    assert excerpt.endswith("…")


@pytest.mark.anyio
async def test_report_contains_no_configured_secret() -> None:
    document = valid_document()
    document["metadata"] = {"note": "safe-metadata"}
    result = await report(
        document,
        {
            "refund": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.AUTHENTICATION,
                    code="auth",
                    message="invalid api key",
                    retryable=False,
                )
            )
        },
    )
    serialized = result.model_dump_json()

    assert "api key" in serialized  # provider message is retained
    assert "sk-" not in serialized  # no credential-like tokens are present
    assert result.gate_outcome.value == "error"
