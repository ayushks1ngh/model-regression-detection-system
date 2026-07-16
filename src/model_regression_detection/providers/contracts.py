"""Provider-neutral inference contracts."""

from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from model_regression_detection.specification.models import MessageRole


class ProviderModel(BaseModel):
    """Strict immutable base for provider request and response data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class InferenceMessage(ProviderModel):
    """A fully rendered provider-neutral chat message."""

    role: MessageRole
    content: Annotated[str, Field(min_length=1, max_length=100_000)]


class InferenceRequest(ProviderModel):
    """One normalized inference request."""

    request_id: Annotated[str, Field(min_length=1, max_length=200)]
    model_id: Annotated[str, Field(min_length=1, max_length=300)]
    messages: Annotated[tuple[InferenceMessage, ...], Field(min_length=1, max_length=100)]
    temperature: Annotated[float, Field(ge=0.0, le=2.0)]
    max_output_tokens: Annotated[int, Field(ge=1, le=1_000_000)]
    timeout_seconds: Annotated[float, Field(gt=0.0, le=600.0)]


class ErrorCategory(StrEnum):
    """Portable provider failure categories used by future retry policy."""

    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSIENT_UPSTREAM = "transient_upstream"
    CONTENT_POLICY = "content_policy"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class ProviderError(ProviderModel):
    """A normalized provider failure with an explicit retry hint."""

    category: ErrorCategory
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    retryable: bool


class TokenUsage(ProviderModel):
    """Normalized token accounting when supplied by a provider."""

    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_total(self) -> "TokenUsage":
        """Require internally consistent token totals."""
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        return self


class InferenceResult(ProviderModel):
    """Exactly one provider success or typed error result."""

    status: Literal["success", "error"]
    output: Annotated[str | None, Field(max_length=1_000_000)] = None
    resolved_model: Annotated[str | None, Field(max_length=300)] = None
    finish_reason: Annotated[str | None, Field(max_length=100)] = None
    usage: TokenUsage | None = None
    cost: Annotated[float | None, Field(ge=0.0)] = None
    latency_ms: Annotated[float, Field(ge=0.0)]
    error: ProviderError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "InferenceResult":
        """Enforce mutually exclusive success and error fields."""
        if self.status == "success":
            if self.output is None or self.error is not None:
                raise ValueError("success requires output and forbids error")
        elif self.error is None or self.output is not None:
            raise ValueError("error status requires error and forbids output")
        return self


class Provider(Protocol):
    """Minimal async provider port used by the sequential runner."""

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        """Execute one normalized inference request."""
        ...
