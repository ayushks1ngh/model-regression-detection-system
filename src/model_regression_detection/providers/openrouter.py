"""OpenRouter provider adapter implementing the neutral inference port."""

import time
from collections.abc import Callable
from typing import Final

import httpx

from model_regression_detection.providers.contracts import (
    ErrorCategory,
    InferenceRequest,
    InferenceResult,
    ProviderError,
    TokenUsage,
)

_DEFAULT_BASE_URL: Final = "https://openrouter.ai/api/v1"
_MAX_RESPONSE_BYTES: Final = 5 * 1024 * 1024
_RETRYABLE_STATUS: Final = frozenset({408, 409, 429, 500, 502, 503, 504})


def _classify_status(status_code: int) -> tuple[ErrorCategory, bool]:
    """Map an HTTP status to a normalized error category and retry hint."""
    if status_code in {401, 403}:
        return ErrorCategory.AUTHENTICATION, False
    if status_code == 429:
        return ErrorCategory.RATE_LIMITED, True
    if status_code == 400:
        return ErrorCategory.INVALID_REQUEST, False
    if status_code == 422:
        return ErrorCategory.CONTENT_POLICY, False
    if status_code in _RETRYABLE_STATUS:
        return ErrorCategory.TRANSIENT_UPSTREAM, True
    if 500 <= status_code < 600:
        return ErrorCategory.TRANSIENT_UPSTREAM, True
    return ErrorCategory.UNKNOWN, False


def _error(
    category: ErrorCategory,
    code: str,
    message: str,
    retryable: bool,
    latency_ms: float,
) -> InferenceResult:
    """Build a normalized error result with bounded, non-secret detail."""
    return InferenceResult(
        status="error",
        latency_ms=latency_ms,
        error=ProviderError(
            category=category,
            code=code,
            message=message[:1_000],
            retryable=retryable,
        ),
    )


class OpenRouterProvider:
    """Call OpenRouter's chat completions API behind the provider contract."""

    def __init__(
        self,
        api_key_provider: Callable[[], str],
        client: httpx.AsyncClient | None = None,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._api_key_provider = api_key_provider
        self._client = client
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        """Build request headers, resolving the API key at call time."""
        return {
            "Authorization": f"Bearer {self._api_key_provider()}",
            "Content-Type": "application/json",
        }

    def _payload(self, request: InferenceRequest) -> dict[str, object]:
        """Map a normalized request to the OpenRouter request body."""
        return {
            "model": request.model_id,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }

    async def generate(self, request: InferenceRequest) -> InferenceResult:
        """Execute one inference request and normalize the response or error."""
        started = time.perf_counter()
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(request),
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException:
            return _error(
                ErrorCategory.TIMEOUT,
                "timeout",
                "OpenRouter request timed out",
                True,
                self._elapsed_ms(started),
            )
        except httpx.HTTPError as exc:
            return _error(
                ErrorCategory.TRANSIENT_UPSTREAM,
                "transport_error",
                f"OpenRouter transport error: {type(exc).__name__}",
                True,
                self._elapsed_ms(started),
            )
        finally:
            if owns_client:
                await client.aclose()

        return self._normalize(response, self._elapsed_ms(started))

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        """Return elapsed milliseconds since a monotonic start marker."""
        return round((time.perf_counter() - started) * 1000, 3)

    def _normalize(self, response: httpx.Response, latency_ms: float) -> InferenceResult:
        """Convert an HTTP response into a normalized inference result."""
        if response.status_code != httpx.codes.OK:
            category, retryable = _classify_status(response.status_code)
            return _error(
                category,
                f"http_{response.status_code}",
                f"OpenRouter returned HTTP {response.status_code}",
                retryable,
                latency_ms,
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            return _error(
                ErrorCategory.INVALID_REQUEST,
                "response_too_large",
                "OpenRouter response exceeded the size limit",
                False,
                latency_ms,
            )
        try:
            body = response.json()
        except ValueError:
            return _error(
                ErrorCategory.UNKNOWN,
                "invalid_json",
                "OpenRouter returned a non-JSON body",
                False,
                latency_ms,
            )
        return self._parse_success(body, latency_ms)

    def _parse_success(self, body: object, latency_ms: float) -> InferenceResult:
        """Extract output, resolved model, finish reason, and usage."""
        if not isinstance(body, dict):
            return _error(
                ErrorCategory.UNKNOWN,
                "unexpected_body",
                "OpenRouter response was not an object",
                False,
                latency_ms,
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return _error(
                ErrorCategory.UNKNOWN,
                "missing_choices",
                "OpenRouter response contained no choices",
                False,
                latency_ms,
            )
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            return _error(
                ErrorCategory.UNKNOWN,
                "missing_content",
                "OpenRouter choice contained no text content",
                False,
                latency_ms,
            )
        finish_reason = choices[0].get("finish_reason")
        resolved_model = body.get("model")
        return InferenceResult(
            status="success",
            output=content,
            resolved_model=resolved_model if isinstance(resolved_model, str) else None,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=_parse_usage(body.get("usage")),
            latency_ms=latency_ms,
        )


def _parse_usage(usage: object) -> TokenUsage | None:
    """Return normalized usage when both token counts are present and valid."""
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
        return None
    if prompt_tokens < 0 or completion_tokens < 0:
        return None
    return TokenUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
