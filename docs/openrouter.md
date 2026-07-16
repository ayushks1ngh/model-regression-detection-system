# OpenRouter Provider Adapter

Milestone 7 implements the provider-neutral inference port against OpenRouter's chat completions API. It performs one request per case and normalizes the response; retries, concurrency, and cost budgets arrive in later milestones.

## Configuration

The adapter resolves its API key from a caller-supplied provider function at call time, so the credential is never stored on the instance state, serialized, or logged:

```python
from model_regression_detection.providers import OpenRouterProvider

provider = OpenRouterProvider(api_key_provider=lambda: os.environ["MRDS_OPENROUTER_API_KEY"])
```

## Response normalization

- `output`: assistant message content.
- `resolved_model`: provider-reported model identity when present.
- `finish_reason`: provider finish reason when present.
- `usage`: input/output/total tokens only when the provider supplies valid counts; otherwise `null` (never fabricated as zero).
- `latency_ms`: measured client-side round trip.

## Error mapping

| Condition | Category | Retryable |
|---|---|---|
| 401 / 403 | `authentication` | no |
| 400 | `invalid_request` | no |
| 422 | `content_policy` | no |
| 429 | `rate_limited` | yes |
| 408 / 409 / 5xx | `transient_upstream` | yes |
| Client timeout | `timeout` | yes |
| Transport error | `transient_upstream` | yes |
| Non-JSON / malformed body | `unknown` | no |

## Safety

- The API key appears only in the `Authorization` header and never in normalized results, errors, or logs.
- Responses larger than 5 MiB are rejected as an invalid-request error.
- Error messages are bounded and contain no credentials.

## Live smoke test

An opt-in test runs only when both variables are set:

```bash
MRDS_OPENROUTER_LIVE=1 MRDS_OPENROUTER_API_KEY=sk-... \
  uv run pytest tests/test_openrouter.py::test_live_smoke
```

Without them, all OpenRouter tests run offline against a mocked transport.
