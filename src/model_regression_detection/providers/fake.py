"""Deterministic in-memory provider for local execution and tests."""

from dataclasses import dataclass

from model_regression_detection.providers.contracts import (
    ErrorCategory,
    InferenceRequest,
    InferenceResult,
    ProviderError,
    TokenUsage,
)


@dataclass(frozen=True, slots=True)
class FakeResponse:
    """A scripted fake-provider response keyed by request ID."""

    output: str | None = None
    error: ProviderError | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        """Require exactly one scripted outcome."""
        if (self.output is None) == (self.error is None):
            raise ValueError("FakeResponse requires exactly one of output or error")
        if self.input_tokens < 0 or self.output_tokens < 0 or self.latency_ms < 0:
            raise ValueError("FakeResponse usage and latency cannot be negative")


class FakeProvider:
    """Return predefined results without network access or nondeterminism."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self._responses = dict(responses)

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        """Return the response mapped to the request ID or a permanent fixture error."""
        response = self._responses.get(request.request_id)
        if response is None:
            return InferenceResult(
                status="error",
                latency_ms=0.0,
                error=ProviderError(
                    category=ErrorCategory.INVALID_REQUEST,
                    code="fake_response_missing",
                    message=f"No fake response configured for request {request.request_id!r}",
                    retryable=False,
                ),
            )
        if response.error is not None:
            return InferenceResult(
                status="error",
                latency_ms=response.latency_ms,
                error=response.error,
            )
        return InferenceResult(
            status="success",
            output=response.output,
            resolved_model=f"fake/{request.model_id}",
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                total_tokens=response.input_tokens + response.output_tokens,
            ),
            latency_ms=response.latency_ms,
        )
