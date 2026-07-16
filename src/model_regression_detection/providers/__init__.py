"""Provider interfaces and built-in deterministic test adapter."""

from model_regression_detection.providers.contracts import (
    ErrorCategory,
    InferenceMessage,
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderError,
    TokenUsage,
)
from model_regression_detection.providers.fake import FakeProvider, FakeResponse
from model_regression_detection.providers.openrouter import OpenRouterProvider

__all__ = [
    "ErrorCategory",
    "FakeProvider",
    "FakeResponse",
    "InferenceMessage",
    "InferenceRequest",
    "InferenceResult",
    "OpenRouterProvider",
    "Provider",
    "ProviderError",
    "TokenUsage",
]
