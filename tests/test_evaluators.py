"""Tests for all M4 deterministic built-in evaluators."""

import pytest
from pydantic import ValidationError

from model_regression_detection.evaluators import EvaluationResult, EvaluationStatus, evaluate_case
from model_regression_detection.specification.models import (
    EvaluatorDefinition,
    EvaluatorType,
    GoldenCase,
)


def definition(kind: EvaluatorType, name: str = "check") -> EvaluatorDefinition:
    """Build one strict evaluator declaration."""
    return EvaluatorDefinition(name=name, type=kind)


def case(expected: object, evaluator: str = "check") -> GoldenCase:
    """Build one evaluator-focused golden case."""
    return GoldenCase(
        key="case-1",
        inputs={},
        expected=expected,  # type: ignore[arg-type]
        evaluators=(evaluator,),
    )


def evaluate(kind: EvaluatorType, expected: object, output: str) -> EvaluationResult:
    """Execute one evaluator and return its only result."""
    evaluator = definition(kind)
    return evaluate_case(case(expected), output, {evaluator.name: evaluator})[0]


@pytest.mark.parametrize(
    ("kind", "expected", "output", "status"),
    [
        (EvaluatorType.EXACT_MATCH, "Hello", "Hello", EvaluationStatus.PASSED),
        (EvaluatorType.EXACT_MATCH, "Hello", "hello", EvaluationStatus.FAILED),
        (
            EvaluatorType.NORMALIZED_MATCH,
            "Café WORLD",
            "  Cafe\u0301   world  ",
            EvaluationStatus.PASSED,
        ),
        (EvaluatorType.CONTAINS, "30 days", "Refunds take 30 days.", EvaluationStatus.PASSED),
        (EvaluatorType.CONTAINS, "30 days", "No refund.", EvaluationStatus.FAILED),
        (EvaluatorType.REGEX, r"order-\d+", "Your order-42 shipped", EvaluationStatus.PASSED),
        (EvaluatorType.REGEX, r"order-\d+", "No identifier", EvaluationStatus.FAILED),
        (EvaluatorType.JSON_VALID, None, '{"ok":true}', EvaluationStatus.PASSED),
        (EvaluatorType.JSON_VALID, None, "not-json", EvaluationStatus.FAILED),
    ],
)
def test_text_regex_and_json_evaluators(
    kind: EvaluatorType,
    expected: object,
    output: str,
    status: EvaluationStatus,
) -> None:
    result = evaluate(kind, expected, output)

    assert result.status is status


def test_json_schema_passes_and_fails_candidate_output() -> None:
    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    }

    passing = evaluate(EvaluatorType.JSON_SCHEMA, schema, '{"answer":"yes"}')
    failing = evaluate(EvaluatorType.JSON_SCHEMA, schema, '{"answer":4}')

    assert passing.status is EvaluationStatus.PASSED
    assert failing.status is EvaluationStatus.FAILED
    assert "does not satisfy" in failing.explanation


def test_invalid_evaluator_expectations_are_errors() -> None:
    wrong_text = evaluate(EvaluatorType.EXACT_MATCH, 42, "42")
    wrong_schema = evaluate(EvaluatorType.JSON_SCHEMA, "not-a-schema", "{}")
    invalid_schema = evaluate(
        EvaluatorType.JSON_SCHEMA,
        {"type": "definitely-not-a-json-schema-type"},
        "{}",
    )
    invalid_regex = evaluate(EvaluatorType.REGEX, "[", "anything")

    assert wrong_text.status is EvaluationStatus.ERRORED
    assert wrong_text.error_code == "invalid_expected_type"
    assert wrong_schema.error_code == "invalid_schema_type"
    assert invalid_schema.error_code == "invalid_json_schema"
    assert invalid_regex.error_code == "invalid_regex"


def test_provider_error_marks_all_case_evaluators_not_applicable() -> None:
    first = definition(EvaluatorType.EXACT_MATCH, "first")
    second = definition(EvaluatorType.JSON_VALID, "second")
    golden_case = GoldenCase(
        key="case-1",
        inputs={},
        expected="hello",
        evaluators=("first", "second"),
    )

    results = evaluate_case(golden_case, None, {"first": first, "second": second})

    assert [result.status for result in results] == [
        EvaluationStatus.NOT_APPLICABLE,
        EvaluationStatus.NOT_APPLICABLE,
    ]


def test_evidence_is_bounded() -> None:
    result = evaluate(EvaluatorType.EXACT_MATCH, "x" * 600, "y" * 600)

    assert isinstance(result.expected, str)
    assert isinstance(result.observed, str)
    assert len(result.expected) == 501
    assert len(result.observed) == 501
    assert result.expected.endswith("…")


def test_evaluation_result_enforces_error_code_invariant() -> None:
    with pytest.raises(ValidationError, match="requires error_code"):
        EvaluationResult(
            evaluator_name="check",
            evaluator_type=EvaluatorType.EXACT_MATCH,
            status=EvaluationStatus.ERRORED,
            explanation="bad config",
        )
    with pytest.raises(ValidationError, match="only valid"):
        EvaluationResult(
            evaluator_name="check",
            evaluator_type=EvaluatorType.EXACT_MATCH,
            status=EvaluationStatus.FAILED,
            explanation="mismatch",
            error_code="unexpected",
        )


def test_regex_timeout_is_an_evaluator_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def timed_out(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TimeoutError

    monkeypatch.setattr("model_regression_detection.evaluators.builtin.regex.search", timed_out)

    result = evaluate(EvaluatorType.REGEX, "(a+)+$", "a" * 10_000)

    assert result.status is EvaluationStatus.ERRORED
    assert result.error_code == "regex_timeout"
