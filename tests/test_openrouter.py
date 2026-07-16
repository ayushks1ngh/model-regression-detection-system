"""Tests for the OpenRouter provider adapter using a mocked transport."""

import os

import httpx
import pytest

from model_regression_detection.providers import (
    ErrorCategory,
    InferenceMessage,
    InferenceRequest,
    OpenRouterProvider,
)

_SECRET_KEY = "sk-secret-openrouter-key-value"  # noqa: S105 - synthetic test credential


def request(model_id: str = "openai/gpt-4.1-mini") -> InferenceRequest:
    """Build a normalized request fixture."""
    return InferenceRequest(
        request_id="case-1",
        model_id=model_id,
        messages=(InferenceMessage(role="user", content="Hello"),),
        temperature=0.0,
        max_output_tokens=16,
        timeout_seconds=5.0,
    )


def provider_with(handler: httpx.MockTransport) -> OpenRouterProvider:
    """Build an adapter backed by a mocked transport and a static key."""
    client = httpx.AsyncClient(transport=handler)
    return OpenRouterProvider(api_key_provider=lambda: _SECRET_KEY, client=client)


@pytest.mark.anyio
async def test_successful_completion_is_normalized() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == f"Bearer {_SECRET_KEY}"
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-4.1-mini",
                "choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert result.status == "success"
    assert result.output == "Hi there"
    assert result.resolved_model == "openai/gpt-4.1-mini"
    assert result.usage is not None
    assert result.usage.total_tokens == 7


@pytest.mark.anyio
async def test_missing_usage_is_unknown_not_zero() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        del req
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "no usage"}}]},
        )

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert result.status == "success"
    assert result.usage is None


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (401, ErrorCategory.AUTHENTICATION, False),
        (400, ErrorCategory.INVALID_REQUEST, False),
        (422, ErrorCategory.CONTENT_POLICY, False),
        (429, ErrorCategory.RATE_LIMITED, True),
        (503, ErrorCategory.TRANSIENT_UPSTREAM, True),
    ],
)
@pytest.mark.anyio
async def test_http_error_mappings(
    status_code: int,
    category: ErrorCategory,
    retryable: bool,
) -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        del req
        return httpx.Response(status_code, json={"error": "failure"})

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.category is category
    assert result.error.retryable is retryable


@pytest.mark.anyio
async def test_timeout_is_retryable_error() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=req)

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.category is ErrorCategory.TIMEOUT
    assert result.error.retryable is True


@pytest.mark.anyio
async def test_malformed_body_is_error() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        del req
        return httpx.Response(200, json={"choices": []})

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert result.status == "error"
    assert result.error is not None
    assert result.error.category is ErrorCategory.UNKNOWN


@pytest.mark.anyio
async def test_api_key_never_appears_in_result() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        del req
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    result = await provider_with(httpx.MockTransport(handle)).generate(request())

    assert _SECRET_KEY not in result.model_dump_json()


@pytest.mark.anyio
@pytest.mark.skipif(
    not os.environ.get("MRDS_OPENROUTER_LIVE"),
    reason="Live OpenRouter smoke test requires MRDS_OPENROUTER_LIVE and MRDS_OPENROUTER_API_KEY",
)
async def test_live_smoke() -> None:  # pragma: no cover - opt-in network test
    api_key = os.environ["MRDS_OPENROUTER_API_KEY"]
    provider = OpenRouterProvider(api_key_provider=lambda: api_key)

    result = await provider.generate(request())

    assert result.status in {"success", "error"}
