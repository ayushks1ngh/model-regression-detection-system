# Deterministic Local Runner

Milestone 3 adds a provider-neutral inference boundary and a sequential local runner backed by a scripted fake provider. It exists to validate rendering, result accounting, typed provider failures, and CLI behavior without network access.

## Run the example

```bash
uv run mrds run-local examples/evaluation.yaml \
  --responses examples/fake-responses.json \
  --output local-run.json
```

The example intentionally returns one success and one retryable rate-limit error. The command completes successfully because M3 records provider evidence only; evaluator and deployment-gate semantics are introduced in later milestones.

## Behavior

For each golden case, in specification order, the runner:

1. Renders provider-neutral messages from validated prompt variables.
2. Builds and hashes a normalized inference request.
3. Calls the async provider interface exactly once.
4. Stores exactly one terminal success or typed error result.
5. Reports successful and errored case counts.

The fake response document maps each case key to exactly one `output` or `error`. Missing mappings become permanent `invalid_request` errors, preserving one terminal result per case.

## Supported rendering

M3 supports simple Python-style named fields such as `{request}`. Attribute/index access, conversions, and format specifications are rejected. Non-string JSON values render as canonical compact JSON. This intentionally narrow syntax avoids dynamic expression evaluation.

## Explicitly deferred

- Evaluator execution and run-level aggregation/quality gate decisions.
- Regression policies and baseline comparison.
- Retries and concurrency.
- OpenRouter and all external network calls.
- Persistence, workers, reports, and CI outcomes.
- Agent orchestration. Agent version provenance remains present in every specification and run hash, but M3 invokes only the declared model request.
