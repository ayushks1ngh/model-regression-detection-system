# Milestone Implementation Plan

## Status and usage

This document is the implementation source of truth for the approved minimal V1 architecture. Before starting work, update, or validation:

1. Read this file.
2. Work only on the first milestone whose status is `IN PROGRESS` or `NOT STARTED`.
3. Do not begin a later milestone until all acceptance criteria for the current milestone pass.
4. Record validation evidence and known blockers here.
5. Keep every milestone independently runnable and scoped to less than one engineering day.

Status values: `COMPLETE`, `IN PROGRESS`, `BLOCKED`, `NOT STARTED`.

## Current progress

| Milestone | Status | Summary |
|---|---|---|
| M1 | COMPLETE | Runnable API/CLI foundation, typed settings, logging, health endpoint, tests, package, non-root Docker image |
| M2 | COMPLETE | Strict schema-v1 evaluation specification, prompt/model/agent version provenance, safe YAML/JSON loading, canonical hashes, CLI validation |
| M3 | COMPLETE | Deterministic provider contracts, scripted fake adapter, safe rendering, sequential local runner, CLI execution, tests, and docs |
| M4 | IN PROGRESS | Built-in deterministic evaluator implementation and runner integration |
| M5–M24 | NOT STARTED | No implementation work permitted until M4 is complete |

## M1 — Runnable project skeleton

**Status:** COMPLETE

**Scope:** Python package, FastAPI application factory, `/health/live`, CLI version/health commands, strict Pydantic settings, structured logging, pinned dependencies, quality tooling, Docker image, and documentation.

**Tests:** API health, CLI smoke, settings validation, logging, target-version references, and Docker smoke.

**Acceptance criteria:** API and CLI run from a clean environment; format/lint/mypy/tests pass; container runs non-root and serves health.

**Evidence:** 20 tests passed at 95.22% coverage. Docker health returned `200`; runtime UID was `10001`.

## M2 — Evaluation specification contract

**Status:** COMPLETE

**Scope:** Strict schema-v1 models, YAML/JSON loading, canonical configuration/dataset hashes, prompt/model/agent version references, CLI `validate`, example specification, and documentation. No execution.

**Tests:** Valid and invalid schemas, unknown fields/versions, duplicate case keys, target-kind validation, input/evaluator references, safe YAML, hash stability/change, and CLI validation.

**Acceptance criteria:** Valid example passes; errors are actionable; equivalent documents hash identically; semantic changes alter the appropriate hash; unknown versions fail closed.

**Evidence:** 35 tests passed at 90.93% coverage; Ruff and strict mypy passed; example validation and wheel/sdist build passed.

## M3 — Deterministic local fake-provider runner

**Status:** COMPLETE

**Scope:** Provider-neutral request/result/error contracts, deterministic fake provider, strict fake fixtures, safe prompt rendering, sequential local runner, CLI `run-local`, tests, and documentation. No OpenRouter, evaluator execution, persistence, or policy decisions.

**Tests:** Fake success/error/missing response, typed error preservation, one terminal result per case, stable order, partial failures, deterministic replay, safe rendering, CLI output, and invalid fixtures.

**Acceptance criteria:** Every case produces one terminal result; errors remain separate from quality outcomes; repeat runs are identical; all repository checks and example smoke run pass.

**Evidence:** 49 tests passed at 93.32% coverage. Ruff formatting/lint, strict mypy, deterministic CLI JSON smoke, and wheel/sdist build passed. Every scripted and missing provider outcome remains a typed terminal result.

## M4 — Built-in deterministic evaluators

**Status:** NOT STARTED

Implement exact, normalized, contains, bounded regex, JSON-valid, and JSON-Schema evaluators with deterministic evidence and tests.

**Acceptance:** Evaluators are deterministic; malformed evaluator configuration is an error, not a failed assertion; regex is bounded; all checks pass.

## M5 — Local aggregation and fixed gate policy

**Status:** NOT STARTED

Aggregate pass/error/critical-case/usage metrics and implement fixed pass/fail/error policy semantics.

**Acceptance:** Quality failures, execution errors, and passes are distinct; threshold boundaries and deterministic replay pass tests.

## M6 — Local JSON report

**Status:** NOT STARTED

Produce a versioned, bounded, redacted JSON report with provenance, decisions, metrics, cases, and usage.

**Acceptance:** Schema and golden fixtures pass; secrets are absent; ordering is stable.

## M7 — OpenRouter provider adapter

**Status:** NOT STARTED

Add OpenRouter behind the M3 provider port with normalized responses, timeouts, usage/cost capture, typed errors, and mocked contract tests.

**Acceptance:** Success and all required failure mappings pass; secrets never leak; absent cost remains unknown.

## M8 — Per-run execution limits

**Status:** NOT STARTED

Add case, token, concurrency, estimated-cost, and known actual-cost caps.

**Acceptance:** Preflight/runtime limits fail safely as execution errors and prevent excess new calls.

## M9 — PostgreSQL persistence

**Status:** NOT STARTED

Add the minimal project/run/job/attempt/result/baseline/artifact schema, migrations, and repositories.

**Acceptance:** Clean migration and reconstruction pass; constraints prevent duplicates; transactions do not leave partial runs.

## M10 — Run submission and status API

**Status:** NOT STARTED

Add run submission/status endpoints, immutable snapshots, idempotency, source metadata, and atomic job creation.

**Acceptance:** Idempotency and conflict behavior pass; no incomplete job manifest can be committed.

## M11 — PostgreSQL-backed worker

**Status:** NOT STARTED

Add leased asynchronous job claiming, provider execution, result persistence, and graceful shutdown.

**Acceptance:** Multiple workers cannot select duplicate evidence; API does not execute provider calls.

## M12 — Retries and lease recovery

**Status:** NOT STARTED

Add bounded retry/backoff, heartbeat, lease reclamation, and stale-owner protection.

**Acceptance:** Retryable/permanent behavior and crash recovery pass without overwriting selected evidence.

## M13 — Run finalization and restart recovery

**Status:** NOT STARTED

Persist aggregates/decisions, finalize states, and reconcile stranded runs.

**Acceptance:** Case accounting is exact; finalization is idempotent; restarts do not strand recoverable runs.

## M14 — Explicit baseline promotion

**Status:** NOT STARTED

Add named revisioned baselines, promotion reasons, eligibility, concurrency control, and frozen resolution.

**Acceptance:** Exactly one concurrent promotion wins; ineligible/cross-project promotion fails; existing runs never move baselines.

## M15 — Candidate-versus-baseline comparison

**Status:** NOT STARTED

Pair stable case keys, enforce compatibility, classify deltas, and apply baseline-drop rules.

**Acceptance:** Reordering is safe; missing/incompatible evidence is explicit; critical regressions cannot be hidden.

## M16 — Safe HTML report

**Status:** NOT STARTED

Generate self-contained escaped reports with CSP, provenance, decisions, deltas, errors, and case diffs.

**Acceptance:** Injection corpus is inert; every blocking rule is explained; artifact hashes match.

## M17 — CLI wait and CI exit contract

**Status:** NOT STARTED

Add submit/wait/status/download commands, bounded polling, machine output, and distinct exit codes.

**Acceptance:** CI distinguishes pass, regression, system error, invalid request, and client timeout.

## M18 — Reusable GitHub Actions workflow

**Status:** NOT STARTED

Wrap the CLI in a least-privilege reusable workflow with summaries, outputs, and artifacts.

**Acceptance:** Pass succeeds; regression and provider outage block for distinct reasons; secrets remain masked.

## M19 — Slack notification

**Status:** NOT STARTED

Send redacted, bounded, retryable terminal-run messages with decision summary and report URL.

**Acceptance:** Notification failure cannot change gate outcome; successful delivery is deduplicated.

## M20 — Cancellation and operational controls

**Status:** NOT STARTED

Add idempotent cancellation, deadlines, late-result handling, and stale-run reconciliation.

**Acceptance:** No new calls start after observed cancellation; partial evidence remains; late output cannot pass a cancelled run.

## M21 — Authentication and project isolation

**Status:** NOT STARTED

Add hashed project tokens, scoped access, rotation/revocation, basic rate limiting, and privileged-action audit.

**Acceptance:** Cross-project identifier substitution always fails; plaintext tokens are never stored.

## M22 — Production-like Docker Compose deployment

**Status:** NOT STARTED

Add API/worker/PostgreSQL topology, health, persistence, migration command, graceful shutdown, and backup/restore procedure.

**Acceptance:** Clean launch, restart persistence, non-root runtime, and restore smoke all pass.

## M23 — V1 security and reliability hardening

**Status:** NOT STARTED

Add size limits, operational metrics, structured correlation, scans, fault tests, and runbooks.

**Acceptance:** No secret canary leakage; malicious/oversized input fails safely; recovery scenarios and security gate pass.

## M24 — MVP release gate

**Status:** NOT STARTED

Create end-to-end release fixtures, checklist, known limitations, and warning-only rollout configuration.

**Acceptance:** Deliberate regression blocks with exact evidence; provider outage blocks as error; restart, baseline, reporting, cost, isolation, and operational checks pass.
