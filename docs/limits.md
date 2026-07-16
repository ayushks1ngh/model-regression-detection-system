# Per-Run Execution Limits

Milestone 8 adds optional bounded limits to an evaluation specification. Preflight limits reject a run before any provider call; runtime limits stop new calls safely. All limit outcomes are execution errors, never quality failures.

## Configuration

```yaml
limits:
  max_cases: 500
  max_output_tokens: 256
  max_concurrency: 1
  max_estimated_cost: 5.0
  estimated_cost_per_case: 0.002
  max_total_cost: 5.0
```

All fields are optional and bounded. When omitted, only the model's own `max_output_tokens` applies and no cost or case caps are enforced.

## Enforcement

- **max_cases:** Runs with more cases than allowed are rejected before execution with `max_cases_exceeded`.
- **max_estimated_cost:** When `estimated_cost_per_case` is provided, the run is rejected before execution if the estimate exceeds the cap.
- **max_output_tokens:** Each request uses the smaller of the model setting and this limit.
- **max_total_cost:** Once known cumulative provider cost reaches the cap, every remaining case receives a `budget_exceeded` error instead of a provider call.

Unknown provider cost is treated as zero for accumulation only because it cannot be counted; it never fabricates spend. The concurrency field is reserved; the local runner remains sequential until a later milestone.

## Outcome semantics

Preflight rejection raises a limit error that the CLI reports with exit code 2 (execution error). Runtime budget exhaustion produces a `budget_exceeded` provider error, which the policy engine treats as an execution error, keeping quality `fail` and system `error` distinct.

## Verify

```bash
uv run pytest tests/test_limits.py
```
