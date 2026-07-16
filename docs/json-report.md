# Local JSON Report

Milestone 6 produces a versioned, self-describing JSON report from a local evaluation. It renders existing evidence deterministically; it does not re-run cases, change gate outcomes, or contact any provider.

## Generate a report

```bash
uv run mrds run-local examples/evaluation.yaml \
  --responses examples/fake-responses.json \
  --report report.json
```

`--output` still writes the raw run/gate envelope; `--report` writes the versioned report. Both can be used together.

## Structure

- `schema_version`: currently `"1"`.
- `generator_version`: the producing package version.
- `gate_outcome`: `pass`, `fail`, or `error`.
- `provenance`: suite, configuration/dataset hashes, and prompt, model, and agent version references.
- `metrics`: aggregate case counts, rates, latency, and known token usage.
- `rules`: ordered fixed-policy decisions with observed values and thresholds.
- `cases`: per-case outcome, provider status, resolved model, latency, bounded output excerpt, provider error, and bounded evaluator evidence.
- `metadata`: specification metadata copied verbatim.

## Guarantees

- Cases preserve specification order; the report is stable across identical runs.
- Provider output excerpts are bounded to 1,000 characters plus a truncation marker; the underlying case outcome is unaffected.
- The report carries no API tokens or configured secrets. Provider error messages are retained as evidence but contain no credentials by contract.
- The schema version is explicit so downstream consumers can detect changes.

## Deferred

M6 does not render HTML, compare against a baseline, or persist artifacts. Those arrive in later milestones.
