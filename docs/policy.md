# Local Aggregation and Fixed Gate Policy

Milestone 5 derives case outcomes and a deterministic local deployment-gate decision from provider and evaluator evidence. It does not compare against a historical baseline; baseline-relative rules are explicitly `not_applicable` until that capability is implemented.

## Case outcome precedence

1. Provider error, required evaluator error, or required evaluator `not_applicable` → case `error`.
2. Any required evaluator failure → case `failed`.
3. Otherwise → case `passed`.

Optional evaluator failures and errors remain visible in evidence but do not change the case outcome.

## Gate precedence

1. Error rate above `maximum_error_rate` or missing valid evidence for a critical case → gate `error`.
2. Minimum pass-rate or critical-quality rule violation → gate `fail`.
3. Otherwise → gate `pass`.

This distinction is intentional: `fail` means valid evidence showed unacceptable quality; `error` means quality could not be established.

## Fixed ordered rules

- `maximum_error_rate`
- `critical_case_evidence`
- `minimum_pass_rate`
- `critical_cases_must_pass`
- `maximum_pass_rate_drop` — `not_applicable` in M5
- `maximum_latency_increase_percent` — `not_applicable` in M5
- `maximum_cost_increase_percent` — `not_applicable` in M5

Every decision records observed value, threshold, unit, explanation, and affected case keys where available.

## Aggregates

M5 records passed/failed/error case counts and rates, critical failures/errors, total provider latency, known input/output/total tokens, and the number of cases with unknown usage. Cost is not invented when unavailable.

## Verify

```bash
uv run pytest tests/test_policy.py tests/test_execution.py
uv run mrds run-local examples/evaluation.yaml \
  --responses examples/fake-responses.json \
  --output local-run.json
```

Inspect `gate` in the generated result. The default example produces gate `error` because one provider response is rate-limited and the policy allows only a 1% error rate.
