"""Built-in deterministic evaluator implementations."""

import json
import unicodedata
from collections.abc import Callable

import regex
from jsonschema import SchemaError
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for
from pydantic import JsonValue

from model_regression_detection.evaluators.models import EvaluationResult, EvaluationStatus
from model_regression_detection.specification.models import (
    EvaluatorDefinition,
    EvaluatorType,
    GoldenCase,
)

_REGEX_TIMEOUT_SECONDS = 0.05
_MAX_EVIDENCE_TEXT = 500
EvaluatorFunction = Callable[[EvaluatorDefinition, GoldenCase, str], EvaluationResult]


def _bounded(value: str) -> str:
    """Bound untrusted text evidence while preserving a visible truncation marker."""
    if len(value) <= _MAX_EVIDENCE_TEXT:
        return value
    return f"{value[:_MAX_EVIDENCE_TEXT]}…"


def _text_expected(evaluator: EvaluatorDefinition, case: GoldenCase) -> str | EvaluationResult:
    """Return a string expectation or an evaluator-configuration error."""
    if not isinstance(case.expected, str):
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.ERRORED,
            explanation="Evaluator requires a string expected value",
            expected=case.expected,
            error_code="invalid_expected_type",
        )
    return case.expected


def _normalize(value: str) -> str:
    """Apply documented deterministic Unicode, whitespace, and case normalization."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _text_result(
    evaluator: EvaluatorDefinition,
    expected: str,
    output: str,
    passed: bool,
    operation: str,
) -> EvaluationResult:
    """Build bounded evidence for a deterministic text assertion."""
    return EvaluationResult(
        evaluator_name=evaluator.name,
        evaluator_type=evaluator.type,
        status=EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED,
        explanation=(
            f"Output {operation} expected text"
            if passed
            else f"Output did not {operation} expected text"
        ),
        expected=_bounded(expected),
        observed=_bounded(output),
    )


def _exact(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    expected = _text_expected(evaluator, case)
    if isinstance(expected, EvaluationResult):
        return expected
    return _text_result(evaluator, expected, output, output == expected, "exactly match")


def _normalized(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    expected = _text_expected(evaluator, case)
    if isinstance(expected, EvaluationResult):
        return expected
    return _text_result(
        evaluator,
        expected,
        output,
        _normalize(output) == _normalize(expected),
        "match normalized",
    )


def _contains(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    expected = _text_expected(evaluator, case)
    if isinstance(expected, EvaluationResult):
        return expected
    return _text_result(evaluator, expected, output, expected in output, "contain")


def _regex(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    pattern = _text_expected(evaluator, case)
    if isinstance(pattern, EvaluationResult):
        return pattern
    try:
        matched = regex.search(pattern, output, timeout=_REGEX_TIMEOUT_SECONDS) is not None
    except regex.error as exc:
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.ERRORED,
            explanation=f"Invalid regular expression: {_bounded(str(exc))}",
            expected=_bounded(pattern),
            error_code="invalid_regex",
        )
    except TimeoutError:
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.ERRORED,
            explanation="Regular expression exceeded the execution timeout",
            expected=_bounded(pattern),
            error_code="regex_timeout",
        )
    return _text_result(evaluator, pattern, output, matched, "match regular expression")


def _parse_output(
    evaluator: EvaluatorDefinition,
    output: str,
) -> tuple[JsonValue, EvaluationResult | None]:
    """Parse candidate output as JSON, returning quality failure evidence on invalid JSON."""
    try:
        return json.loads(output), None
    except json.JSONDecodeError as exc:
        return None, EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.FAILED,
            explanation=f"Output is not valid JSON at line {exc.lineno}, column {exc.colno}",
            observed=_bounded(output),
        )


def _json_valid(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    del case
    parsed, failure = _parse_output(evaluator, output)
    if failure is not None:
        return failure
    return EvaluationResult(
        evaluator_name=evaluator.name,
        evaluator_type=evaluator.type,
        status=EvaluationStatus.PASSED,
        explanation="Output is valid JSON",
        observed=parsed,
    )


def _json_schema(evaluator: EvaluatorDefinition, case: GoldenCase, output: str) -> EvaluationResult:
    parsed, failure = _parse_output(evaluator, output)
    if failure is not None:
        return failure
    if not isinstance(case.expected, dict):
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.ERRORED,
            explanation="JSON Schema evaluator requires an object expected value",
            expected=case.expected,
            error_code="invalid_schema_type",
        )
    try:
        validator_class = validator_for(case.expected)
        validator_class.check_schema(case.expected)
        validator_class(case.expected).validate(parsed)
    except SchemaError as exc:
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.ERRORED,
            explanation=f"Expected JSON Schema is invalid: {_bounded(exc.message)}",
            expected=case.expected,
            error_code="invalid_json_schema",
        )
    except JsonSchemaValidationError as exc:
        return EvaluationResult(
            evaluator_name=evaluator.name,
            evaluator_type=evaluator.type,
            status=EvaluationStatus.FAILED,
            explanation=f"Output does not satisfy JSON Schema: {_bounded(exc.message)}",
            expected=case.expected,
            observed=parsed,
        )
    return EvaluationResult(
        evaluator_name=evaluator.name,
        evaluator_type=evaluator.type,
        status=EvaluationStatus.PASSED,
        explanation="Output satisfies JSON Schema",
        expected=case.expected,
        observed=parsed,
    )


_EVALUATORS: dict[EvaluatorType, EvaluatorFunction] = {
    EvaluatorType.EXACT_MATCH: _exact,
    EvaluatorType.NORMALIZED_MATCH: _normalized,
    EvaluatorType.CONTAINS: _contains,
    EvaluatorType.REGEX: _regex,
    EvaluatorType.JSON_VALID: _json_valid,
    EvaluatorType.JSON_SCHEMA: _json_schema,
}


def evaluate_case(
    case: GoldenCase,
    output: str | None,
    definitions: dict[str, EvaluatorDefinition],
) -> tuple[EvaluationResult, ...]:
    """Evaluate one successful output or mark assertions inapplicable on provider error."""
    results: list[EvaluationResult] = []
    for evaluator_name in case.evaluators:
        evaluator = definitions[evaluator_name]
        if output is None:
            results.append(
                EvaluationResult(
                    evaluator_name=evaluator.name,
                    evaluator_type=evaluator.type,
                    status=EvaluationStatus.NOT_APPLICABLE,
                    explanation="Provider did not produce output",
                )
            )
            continue
        results.append(_EVALUATORS[evaluator.type](evaluator, case, output))
    return tuple(results)
