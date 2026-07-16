# Evaluation Specification v1

Milestone 2 defines the versioned input contract consumed by future runners. It performs validation and hashing only; it does not call models, execute evaluators, compare baselines, or persist runs.

## Validate a specification

```bash
uv run mrds validate examples/evaluation.yaml
uv run mrds validate examples/evaluation.yaml --json
```

A successful validation prints the schema version, suite, counts, target-version identities, and canonical SHA-256 hashes for:

- **Configuration:** the specification excluding golden cases.
- **Dataset:** the ordered golden-case manifest.

These hashes are deterministic across YAML/JSON formatting and mapping-key order. Case and message order remain significant because they are part of the declared manifest.

## Required structure

- `schema_version`: currently exactly `"1"`; unknown versions fail closed.
- `suite`: stable suite identifier.
- `prompt`: immutable prompt-version reference, message templates, and declared variables.
- `model`: immutable model-version reference and bounded OpenRouter generation settings.
- `agent`: optional immutable agent-version reference. It permits agent-version provenance now; agent execution is intentionally deferred.
- `evaluators`: one or more built-in evaluator declarations.
- `cases`: one or more uniquely keyed golden cases.
- `policy`: fixed initial regression-policy thresholds.
- `metadata`: bounded JSON-compatible project information.

Every target reference has `kind`, `target_id`, `version`, and a lowercase 64-character SHA-256 `content_hash`. This gives prompt, model, and agent versions the same provenance contract.

## Validation guarantees

- Unknown fields are rejected at every level.
- Models are immutable after validation.
- Case keys, evaluator names, prompt variables, tags, and evaluator references are unique where required.
- Each case supplies exactly the declared prompt inputs.
- Each case references only declared evaluators.
- Numeric policy and model limits are bounded.
- YAML uses `safe_load`; executable/custom YAML tags are rejected.
- Input files must be UTF-8, use `.json`, `.yaml`, or `.yml`, and be at most 10 MiB.

## Deferred behavior

M2 does not verify that a supplied target content hash matches an external registry or repository, parse template placeholders, execute an agent, call OpenRouter, or run evaluator logic. Those require later milestone contracts and runtime behavior.
