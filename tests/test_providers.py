"""Tests for provider-neutral contracts and deterministic fake behavior."""

import pytest
from pydantic import ValidationError

from model_regression_detection.providers import (
    ErrorCategory,
    FakeProvider,
    FakeResponse,
    InferenceMessage,
    InferenceRequest,
    InferenceResult,
    ProviderError,
    TokenUsage,
)


def request(request_id: str = "case-1") -> InferenceRequest:
    """Build a valid normalized request fixture."""
    return InferenceRequest(
        request_id=request_id,
        model_id="test/model",
        messages=(InferenceMessage(role="user", content="Hello"),),
        temperature=0.0,
        max_output_tokens=10,
        timeout_seconds=5.0,
    )


@pytest.mark.anyio
async def test_fake_provider_returns_deterministic_success() -> None:
    provider = FakeProvider(
        {"case-1": FakeResponse(output="Hello", input_tokens=2, output_tokens=1, latency_ms=4.0)}
    )

    first = await provider.generate(request())
    second = await provider.generate(request())

    assert first == second
    assert first.status == "success"
    assert first.usage == TokenUsage(input_tokens=2, output_tokens=1, total_tokens=3)


@pytest.mark.anyio
async def test_fake_provider_preserves_typed_retryable_error() -> None:
    error = ProviderError(
        category=ErrorCategory.RATE_LIMITED,
        code="rate_limited",
        message="Try later",
        retryable=True,
    )
    provider = FakeProvider({"case-1": FakeResponse(error=error, latency_ms=2.0)})

    result = await provider.generate(request())

    assert result.status == "error"
    assert result.error == error
    assert result.output is None


@pytest.mark.anyio
async def test_missing_fake_response_is_permanent_invalid_request() -> None:
    result = await FakeProvider({}).generate(request("missing"))

    assert result.status == "error"
    assert result.error is not None
    assert result.error.category is ErrorCategory.INVALID_REQUEST
    assert result.error.retryable is False


def test_result_requires_exactly_one_outcome() -> None:
    with pytest.raises(ValidationError):
        InferenceResult(status="success", latency_ms=0.0)

    with pytest.raises(ValidationError):
        InferenceResult(
            status="error",
            output="invalid",
            error=ProviderError(
                category=ErrorCategory.UNKNOWN,
                code="unknown",
                message="unknown",
                retryable=False,
            ),
            latency_ms=0.0,
        )


def test_token_usage_requires_consistent_total() -> None:
    with pytest.raises(ValidationError, match="total_tokens"):
        TokenUsage(input_tokens=2, output_tokens=3, total_tokens=99)


def test_fake_response_requires_one_outcome_and_nonnegative_usage() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FakeResponse()
    with pytest.raises(ValueError, match="cannot be negative"):
        FakeResponse(output="ok", input_tokens=-1)
