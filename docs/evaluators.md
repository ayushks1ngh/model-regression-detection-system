# Built-in Evaluators

Milestone 4 executes deterministic assertions after a successful provider response. It adds evidence only; run-level aggregation and deployment gate decisions remain deferred to M5.

## Supported evaluator types

| Type | Expected value | Pass condition |
|---|---|---|
| `exact_match` | String | Output is byte-for-byte equal |
| `normalized_match` | String | Unicode NFKC, case-folded, whitespace-collapsed values are equal |
| `contains` | String | Expected text occurs in output, case-sensitive |
| `regex` | String pattern | Pattern finds a match within a 50 ms execution timeout |
| `json_valid` | Ignored | Output parses as JSON |
| `json_schema` | JSON Schema object | Parsed output validates against the schema |

## Outcome semantics

- `passed`: Valid evaluator configuration and candidate output met the assertion.
- `failed`: Valid evaluator configuration and candidate output did not meet the assertion. Invalid candidate JSON is a quality failure.
- `errored`: The expected value, regex, or JSON Schema is malformed; quality was not established.
- `not_applicable`: The provider produced no output, so the assertion was not executed.

Evaluator errors must never be converted to quality failures. Provider errors remain in provider evidence and make all case evaluators `not_applicable`.

## Evidence safety

Text expectations and observed outputs are bounded to 500 characters plus a truncation marker. Regex execution uses a strict timeout. Evaluators are selected from a fixed enum; M4 does not load custom code or plugins.

## Run locally

```bash
uv run mrds run-local examples/evaluation.yaml \
  --responses examples/fake-responses.json \
  --output local-run.json
```

Inspect `cases[].evaluations` in the generated JSON. The current example has a passing `contains` assertion for `refund-policy`; `greeting` has a provider error and therefore a `not_applicable` assertion.
