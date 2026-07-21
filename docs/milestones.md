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
| M4 | COMPLETE | Six deterministic evaluators, bounded evidence, provider-error handling, runner integration, tests, and docs |
| M5 | COMPLETE | Deterministic case aggregation and fixed pass/fail/error gate with ordered rule evidence |
| M6 | COMPLETE | Versioned, bounded, deterministic local JSON report with provenance and redaction |
| M7 | COMPLETE | OpenRouter adapter with normalized responses, typed errors, secret safety, and mocked contract tests |
| M8 | COMPLETE | Preflight case/cost rejection, per-request token cap, and runtime hard cost cap as execution errors |
| M9 | COMPLETE | Async PostgreSQL schema, Alembic migrations, run repository, and readiness check |
| M10 | COMPLETE | Run submission API with immutable snapshot, idempotency, and status retrieval |
| M11 | COMPLETE | PostgreSQL-backed worker with atomic claim, lease expiry reclaim, and graceful shutdown |
| M12 | COMPLETE | Retries, heartbeat lease renewal, and provider retry/backoff |
| M13 | IN PROGRESS | Run finalization and restart recovery |
| M14 | COMPLETE | Explicit baseline promotion with atomic concurrency control |
| M15 | COMPLETE | Candidate-versus-baseline comparison with drop-rule evaluation |
| M16 | COMPLETE | Self-contained safe HTML report with CSP, provenance, deltas, and case diffs |
| M17 | COMPLETE | CLI submit/status/wait/download with distinct exit codes for CI |
| M18 | COMPLETE | Reusable GitHub Actions workflow with summaries, artifacts, and distinct failure modes |
| M19 | COMPLETE | Bounded, retryable Slack notification with decision summary |
| M20 | COMPLETE | Idempotent cancellation, cancellation token, worker detection, partial evidence |
| M21 | COMPLETE | Bearer token auth, scoped access, rate limiter, token management API |
| M22–M24 | NOT STARTED | No implementation work permitted until M21 is complete |

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

**Status:** COMPLETE

Implement exact, normalized, contains, bounded regex, JSON-valid, and JSON-Schema evaluators with deterministic evidence and tests.

**Acceptance:** Evaluators are deterministic; malformed evaluator configuration is an error, not a failed assertion; regex is bounded; all checks pass.

**Evidence:** 64 tests passed at 93.53% coverage. Ruff, strict mypy, evaluator smoke assertions, and wheel/sdist builds passed. Provider failures produce `not_applicable`; malformed expectations produce `errored`.

## M5 — Local aggregation and fixed gate policy

**Status:** COMPLETE

Aggregate pass/error/critical-case/usage metrics and implement fixed pass/fail/error policy semantics.

**Acceptance:** Quality failures, execution errors, and passes are distinct; threshold boundaries and deterministic replay pass tests.

**Evidence:** 72 tests passed at 94.18% coverage. Ruff, strict mypy, deterministic gate replay, run/gate smoke assertions, and package builds passed. Baseline-relative rules are `not_applicable` until M15. A circular import between runner and policy was resolved by separating `execution/models.py` evidence from `execution/report.py` orchestration.

## M6 — Local JSON report

**Status:** COMPLETE

Produce a versioned, bounded, redacted JSON report with provenance, decisions, metrics, cases, and usage.

**Acceptance:** Schema and golden fixtures pass; secrets are absent; ordering is stable.

**Evidence:** 78 tests passed at 94.69% coverage. Ruff, strict mypy, redaction/ordering/truncation tests, CLI report smoke, and package builds passed.

## M7 — OpenRouter provider adapter

**Status:** COMPLETE

Add OpenRouter behind the M3 provider port with normalized responses, timeouts, usage/cost capture, typed errors, and mocked contract tests.

**Acceptance:** Success and all required failure mappings pass; secrets never leak; absent cost remains unknown.

**Evidence:** 88 tests passed (1 opt-in live test skipped) at 93.30% coverage. Ruff, strict mypy, mocked-transport contract tests, secret-leak assertion, and package builds passed. `httpx` was promoted from a dev to a runtime dependency, fixing a latent CLI import gap.

## M8 — Per-run execution limits

**Status:** COMPLETE

Add case, token, concurrency, estimated-cost, and known actual-cost caps.

**Acceptance:** Preflight/runtime limits fail safely as execution errors and prevent excess new calls.

**Evidence:** 94 tests passed (1 opt-in live test skipped) at 93.16% coverage. Ruff, strict mypy, preflight/token/cost-cap tests, and package builds passed. Over-limit runs produce execution errors, never quality failures; unknown cost is never fabricated as spend.

## M9 — PostgreSQL persistence

**Status:** COMPLETE

Add the minimal project/run/job/attempt/result/baseline/artifact schema, migrations, and repositories.

**Acceptance:** Clean migration and reconstruction pass; constraints prevent duplicates; transactions do not leave partial runs.

**Evidence:** 101 tests passed (2 opt-in skips) at 93.17% coverage. Real PostgreSQL validated the asyncpg round-trip and Alembic upgrade/downgrade; offline tests use in-memory SQLite. Duplicate case keys and partial-transaction rollback are covered. Async lazy-load was fixed with eager `selectinload`; migrations use `psycopg2-binary`.

## M10 — Run submission and status API

**Status:** COMPLETE

Add run submission/status endpoints, immutable snapshots, idempotency, source metadata, and atomic job creation.

**Acceptance:** Idempotency and conflict behavior pass; no incomplete job manifest can be committed.

**Evidence:** 113 tests passed (2 opt-in skips) at 92.97% coverage. Ruff, strict mypy, and package build passed. Both migrations (`0001_initial`, `0002_run_lifecycle`) validated against real PostgreSQL including upgrade, downgrade, and re-upgrade. Run state (`created`/`completed`/`failed`) is separate from gate outcome, which stays `null` until completion. `RunRepository` was extended from single-shot `save_report` to a `create_run`/`complete_run` lifecycle with project-scoped idempotency.

## M11 — PostgreSQL-backed worker

**Status:** COMPLETE

Add leased asynchronous job claiming, provider execution, result persistence, and graceful shutdown.

**Acceptance:** Multiple workers cannot select duplicate evidence; API does not execute provider calls.

**Evidence:** 120 tests passed (3 opt-in skips) at 90.67% coverage. Ruff, strict mypy, and package build passed. Verified against real PostgreSQL: full end-to-end API-submit → worker-execute → status-complete flow, atomic claim exclusivity, lease expiry reclaim, and stale-worker rejection on completion.

**Defect found and fixed:** `create_run` added the run row and its idempotency record to the same flush. PostgreSQL enforces foreign-key insert ordering strictly and raised `ForeignKeyViolationError` on every idempotent submission; SQLite did not enforce this, so the offline test suite never caught it. Fixed by flushing the run insert before the idempotency record. Added a Postgres-only regression test.

## M12 — Retries and lease recovery

**Status:** COMPLETE

**Scope:** Bounded retry/backoff via RetryProvider wrapper, worker heartbeat renewal during execution, expontential-backoff retry for transient provider errors, background heartbeat loop that extends the lease every `lease_seconds / 3` seconds, and stale-owner protection enforced by `complete_run` worker-id matching.

**Tests:** RetryProvider retries on retryable errors, stops on permanent errors, stops after max_retries exhausted, immediate success without retries. Heartbeat extends lease during execution. Run with retryable provider succeeds end-to-end. Template render errors produce errored cases instead of crashing. CLI worker precondition validation tests.

**Acceptance:** Retryable/permanent behavior and crash recovery pass without overwriting selected evidence.

## M13 — Run finalization and restart recovery

**Status:** COMPLETE

**Scope:** Startup reconciliation of stranded runs (running with expired leases, or stale created runs), idempotent reconcile method on RunRepository, and worker startup sweep.

**Tests:** Stranded running runs are failed with correct metadata; active leases are skipped; reconcile is idempotent; stale created runs can be optionally failed; worker reconciles on startup.

**Acceptance:** Case accounting is exact; finalization is idempotent; restarts do not strand recoverable runs.

## M14 — Explicit baseline promotion

**Status:** COMPLETE

**Scope:** Database table `baseline_channels` (migration 0004) with project-scoped unique channels, ORM model, repository methods (`promote_run`, `get_baseline`, `list_baselines`), REST API (`POST/GET /api/v1/projects/{id}/baselines/{channel}`, `GET /api/v1/projects/{id}/baselines`). Atomic promotion via conditional UPDATE; eligible runs must be `completed` with `gate_outcome=pass`; frozen resolution via immutable channel records.

**Tests:** 5 repository tests (create, ineligible rejection, update existing, idempotent same-run, project-scoped list) + 5 API tests (promote+get, missing run_id, unknown baseline 404, list, 503 without DB).

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

**Status:** COMPLETE

Add idempotent cancellation, deadlines, late-result handling, and stale-run reconciliation.

**Acceptance:** No new calls start after observed cancellation; partial evidence remains; late output cannot pass a cancelled run.

## M21 — Authentication and project isolation

**Status:** COMPLETE

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
