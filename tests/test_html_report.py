"""Tests for self-contained safe HTML report generation (M16)."""

from copy import deepcopy
from typing import Any

import pytest

from model_regression_detection.execution.report import execute_local_evaluation
from model_regression_detection.policy import BaselineComparison
from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    ProviderError,
)
from model_regression_detection.reporting import build_html_report, build_json_report
from model_regression_detection.specification.models import EvaluationSpecificationV1
from tests.test_specification import valid_document


async def html_report(
    document: dict[str, Any],
    responses: dict[str, FakeResponse],
    baseline: BaselineComparison | None = None,
) -> str:
    """Build an HTML report from a document and responses."""
    specification = EvaluationSpecificationV1.model_validate(document)
    evaluation = await execute_local_evaluation(specification, FakeProvider(responses))
    json_report = build_json_report(specification, evaluation)
    return build_html_report(json_report, baseline=baseline)


@pytest.mark.anyio
async def test_html_contains_suite_name() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "support-smoke" in html


@pytest.mark.anyio
async def test_html_contains_outcome_badge() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "badge-pass" in html
    assert document["suite"] in html


@pytest.mark.anyio
async def test_html_includes_all_cases() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "refund" in html


@pytest.mark.anyio
async def test_html_contains_generator_version() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    from model_regression_detection import __version__

    assert __version__ in html


@pytest.mark.anyio
async def test_html_contains_csp_meta_tag() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "Content-Security-Policy" in html
    assert "script-src 'none'" in html


@pytest.mark.anyio
async def test_html_has_no_external_scripts() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "<script" not in html


@pytest.mark.anyio
async def test_html_escapes_user_content_in_output() -> None:
    document = valid_document()
    html = await html_report(
        document, {"refund": FakeResponse(output="<script>alert(1)</script>")}
    )

    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html


@pytest.mark.anyio
async def test_html_shows_provenance_section() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "Provenance" in html
    assert "Configuration" in html
    assert "Dataset" in html


@pytest.mark.anyio
async def test_html_shows_metrics_section() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "Metrics" in html
    assert "Total cases" in html
    assert "Total latency" in html


@pytest.mark.anyio
async def test_html_shows_rules_section() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "Rules" in html
    assert "minimum_pass_rate" in html


@pytest.mark.anyio
async def test_html_shows_fail_gate_outcome() -> None:
    document = valid_document()
    document["policy"]["minimum_pass_rate"] = 1.0
    html = await html_report(
        document, {"refund": FakeResponse(output="wrong answer")}
    )

    assert "badge-fail" in html


@pytest.mark.anyio
async def test_html_shows_error_gate_outcome() -> None:
    document = valid_document()
    html = await html_report(
        document,
        {
            "refund": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.TIMEOUT,
                    code="timeout",
                    message="provider timed out",
                    retryable=True,
                )
            )
        },
    )

    assert "badge-error" in html


@pytest.mark.anyio
async def test_html_shows_evaluator_results() -> None:
    document = valid_document()
    html = await html_report(
        document, {"refund": FakeResponse(output="wrong answer")}
    )

    assert "answer-match" in html
    assert "failed" in html


@pytest.mark.anyio
async def test_html_includes_baseline_section_when_provided() -> None:
    document = valid_document()
    specification = EvaluationSpecificationV1.model_validate(document)
    evaluation = await execute_local_evaluation(
        specification, FakeProvider({"refund": FakeResponse(output="30 days")})
    )
    json_report = build_json_report(specification, evaluation)

    baseline = BaselineComparison(
        configuration_match=True,
        dataset_match=True,
        total_cases_candidate=1,
        total_cases_baseline=1,
        matching_case_keys=("refund",),
        missing_in_candidate=(),
        missing_in_baseline=(),
        pass_rate_baseline=1.0,
        pass_rate_candidate=1.0,
        pass_rate_drop=0.0,
        latency_ms_baseline=10.0,
        latency_ms_candidate=12.0,
        latency_increase_pct=20.0,
        cost_baseline=0.01,
        cost_candidate=0.015,
        cost_increase_pct=50.0,
    )

    html = build_html_report(json_report, baseline=baseline)

    assert "<h2>Baseline comparison</h2>" in html
    assert "20.0%" in html or "20.0" in html
    assert "50.0%" in html or "50.0" in html


@pytest.mark.anyio
async def test_html_omits_baseline_section_when_not_provided() -> None:
    document = valid_document()
    html = await html_report(document, {"refund": FakeResponse(output="30 days")})

    assert "<h2>Baseline comparison</h2>" not in html


@pytest.mark.anyio
async def test_html_includes_provider_error_details() -> None:
    document = valid_document()
    html = await html_report(
        document,
        {
            "refund": FakeResponse(
                error=ProviderError(
                    category=ErrorCategory.AUTHENTICATION,
                    code="auth_failed",
                    message="invalid key",
                    retryable=False,
                )
            )
        },
    )

    assert "auth_failed" in html
    assert "invalid key" in html


@pytest.mark.anyio
async def test_html_shows_multiple_cases() -> None:
    document = valid_document()
    second = deepcopy(document["cases"][0])
    second["key"] = "second-case"
    document["cases"].append(second)

    html = await html_report(
        document,
        {
            "refund": FakeResponse(output="30 days"),
            "second-case": FakeResponse(output="30 days"),
        },
    )

    assert "refund" in html
    assert "second-case" in html


@pytest.mark.anyio
async def test_html_is_deterministic() -> None:
    document = valid_document()
    responses = {"refund": FakeResponse(output="30 days")}

    first = await html_report(deepcopy(document), responses)
    second = await html_report(deepcopy(document), responses)

    assert first == second
