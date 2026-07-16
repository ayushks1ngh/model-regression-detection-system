# Engineering Tasks and Subtasks

## 1. Backlog conventions

This backlog is architecture-level and contains no implementation. IDs are stable for planning. Each task must produce tests, observability, security review, and documentation where relevant. `P0` blocks the first production release; `P1` is important but may follow MVP; `P2` is future.

A task is done only when:

- Its acceptance criteria and linked phase criteria in [roadmap.md](roadmap.md) pass.
- Unit, contract, integration, migration, and failure-path tests appropriate to the change pass.
- Logs/metrics contain correlation identifiers and no payloads/secrets by default.
- API/schema changes are versioned and documented.
- Threat-model changes and operational runbooks are updated.

## 2. Epic map

| Epic | Outcome | Priority | Primary dependencies |
|---|---|---:|---|
| E0 Architecture approval | Decisions and scope are signed off | P0 | None |
| E1 Platform foundation | Reproducible local/CI runtime and quality gates | P0 | E0 |
| E2 Identity and projects | Secure project-scoped control plane | P0 | E1 |
| E3 Versioned authoring | Immutable prompts, datasets, configs, suites | P0 | E2 |
| E4 Provider gateway | Reliable OpenRouter execution behind contracts | P0 | E3 |
| E5 Run orchestration | Durable asynchronous evaluation matrix | P0 | E4 |
| E6 Evaluation and policies | Reproducible scoring and regression decisions | P0 | E5 |
| E7 Reports and history | Auditable human/machine evidence | P0 | E6 |
| E8 CI and notifications | Deployment gate and actionable alerts | P0 | E7 |
| E9 Production hardening | Security, load, recovery, and operations | P0 | E8 |
| E10 Advanced scale | Statistical, provider, and enterprise extensions | P1/P2 | E9 |

## 3. E0 — Architecture approval

### T0.1 Resolve product decisions

- Confirm API/CLI-first MVP versus dashboard.
- Define launch personas, approvers, and baseline promotion policy.
- Approve data classifications allowed through OpenRouter.
- Set initial scale, cost, latency, retention, RPO, and RTO targets.
- Decide whether LLM judge and GitHub App/check-run are launch requirements.

**Acceptance:** Every question in PRD section 12 and architecture section 16 has an owner and recorded decision or explicit deferral.

### T0.2 Record architecture decisions

- Create ADRs for storage, queue authority, snapshots, baselines, state/gate separation, provider contract, artifact storage, and modular boundaries.
- Spike queue/workflow choices against lease, retry, cancellation, priority, and operational requirements.
- Approve threat model and abuse cases.

**Acceptance:** Architecture review signs off; no unresolved P0 decision remains; implementation is authorized explicitly.

### T0.3 Define test strategy

- Build a requirement-to-test traceability matrix.
- Define deterministic fake provider, fault injection, clock control, and canonical fixtures.
- Define report golden-file policy and compatibility contract suites.

**Acceptance:** Each P0 requirement has a planned test level and owner.

## 4. E1 — Platform foundation

### T1.1 Repository and dependency policy

- Establish module boundaries from architecture.
- Pin language/runtime and all direct dependencies.
- Configure formatting, linting, type checking, unit tests, coverage, secret scanning, dependency scanning, and SBOM generation.
- Add contribution and architecture guardrails.

### T1.2 Configuration and secret abstraction

- Define typed environment configuration with startup validation.
- Separate safe configuration from secret references.
- Add local environment-secret adapter and production secret-manager port.
- Implement redaction rules and tests conceptually specified in security requirements.

### T1.3 Container topology

- Define non-root API, worker, scheduler/dispatcher images.
- Add PostgreSQL, Redis, and S3-compatible local topology with health checks and persistent volumes.
- Add deterministic startup/migration flow and graceful shutdown.

### T1.4 Persistence foundation

- Create migration baseline for tenancy, versions, runs, evidence, artifacts, audit, outbox, and idempotency in safe increments.
- Add transaction/session conventions and repository scoping.
- Add migration upgrade/rollback and clean-install tests.

### T1.5 Observability foundation

- Establish structured logging, metrics, tracing, correlation IDs, health/readiness, and redaction.
- Define dashboards and alert naming conventions.

**Epic acceptance:** A clean environment starts from pinned artifacts, migrates automatically under operator control, passes quality/security checks, emits health/telemetry, and never logs seeded test secrets.

## 5. E2 — Identity, authorization, and projects

### T2.1 Authentication

- Implement user/service principal abstraction.
- Issue, hash, rotate, expire, and revoke project service tokens.
- Enforce bounded token scopes and authentication rate limits.

### T2.2 Authorization

- Implement workspace/project resource guards and roles.
- Add negative cross-project tests for every repository/resource family.
- Protect restricted raw-evidence reads with enhanced permission and audit.

### T2.3 Project lifecycle

- Create/list/get/update/archive workspaces and projects.
- Manage provider/model allowlists, data classification, and project limits.
- Add append-only audit events for privileged actions.

**Epic acceptance:** Viewer/runner/editor/approver/admin permissions behave as specified; cross-project ID substitution always fails; revoked CI credentials cannot submit runs.

## 6. E3 — Versioned authoring

### T3.1 Prompt registry

- Create prompt identities and immutable versions.
- Validate strict variables and supported text/chat templates.
- Generate canonical content hash and provenance.
- Prevent edits/deletes of referenced versions.

### T3.2 Golden dataset lifecycle

- Implement draft and revision control.
- Upsert/delete cases in draft; validate unique keys, prompt compatibility, schema, bounds, classification, and assertions.
- Publish atomically to immutable dataset version and ordered manifest hash.
- Add version diff and JSONL import/export contract with row-level errors.

### T3.3 Model configurations

- Create immutable provider/model settings versions.
- Validate parameter bounds and secret references.
- Enforce provider/model/data-classification allowlists.
- Add adapter-specific discriminated configuration schemas.

### T3.4 Evaluator registry

- Define evaluator type contracts and metric declarations.
- Version evaluator configs, rubric/judge refs, parser implementation, and semantic hash.
- Reject semantically incomplete or incompatible definitions.

### T3.5 Regression policy authoring

- Define rule schema for scope, metric, comparator, direction, thresholds, missing evidence, severity, and sample/coverage.
- Validate duplicate IDs, unknown metrics, contradictory thresholds, and unsupported slices.

### T3.6 Suite versioning

- Link published dataset, evaluator, policy, and permitted model/prompt slots.
- Validate project ownership and compatibility.
- Publish immutable suite versions and hashes.

**Epic acceptance:** Any mutation after publication is rejected; two independently canonicalized equivalent definitions hash identically; invalid datasets/policies provide actionable field/row issues; historical versions remain readable.

## 7. E4 — Provider gateway and OpenRouter

### T4.1 Provider-neutral contracts

- Define normalized request, response, usage, model resolution, and typed error models.
- Define adapter capability and health semantics.
- Build an adapter contract suite with fake provider.

### T4.2 OpenRouter adapter

- Map text/chat/structured requests and supported parameters.
- Capture provider request IDs, resolved model metadata, finish reasons, tokens, cost, and safe errors.
- Apply timeout and response-size limits.
- Confirm current OpenRouter API details during implementation against official documentation.

### T4.3 Resilience controls

- Implement retry classification, exponential backoff/jitter, circuit breaker, and retry budgets.
- Implement project/provider/model concurrency and rate limits.
- Ensure auth, invalid request, and policy errors are never blindly retried.

### T4.4 Cost and privacy controls

- Estimate cost before submission when possible.
- Reserve/enforce run/project budget and token caps.
- Reconcile actual and estimated usage; expose unknown cost.
- Redact headers/payloads and constrain worker egress.

**Epic acceptance:** Contract tests pass for success, rate limit, timeout, malformed response, auth failure, upstream failure, cancellation, and missing usage; no fixture secret appears in logs/database/report; cost and attempt evidence reconcile.

## 8. E5 — Durable run orchestration

### T5.1 Run planner and snapshot

- Validate idempotent submission.
- Resolve selectors and baseline channel revision transactionally.
- Materialize candidate × case × evaluator work plan.
- Estimate work/cost and reject over-budget or incompatible runs.
- Persist canonical snapshot, tasks, reservation, and outbox atomically.

### T5.2 Queue/outbox dispatcher

- Dispatch committed work at least once.
- Add priorities, delayed retry, queue-backpressure, and dead-letter handling.
- Ensure queue outage after database commit does not lose work.

### T5.3 Worker leasing and attempts

- Claim logical work idempotently with lease/heartbeat.
- Record every attempt and enforce unique successful selection.
- Handle process crash before/after provider call.
- Add graceful shutdown and lease release/expiry.

### T5.4 Prompt rendering and model execution

- Render strict prompt snapshot with case input in a networkless component.
- Store hashes and retention-controlled bodies.
- Invoke provider gateway and persist attempt/evidence atomically where possible.

### T5.5 Cancellation, deadlines, reconciliation

- Stop scheduling after cancellation request.
- Handle late responses without selecting them for a cancelled gate.
- Reclaim expired leases and finalize stuck runs.
- Expire runs that exceed deadlines and reconcile reservations/usage.

### T5.6 State machine

- Enforce compare-and-set monotonic transitions.
- Emit phase events and durations.
- Separate run state from gate outcome.

**Epic acceptance:** Fault-injection tests kill workers at each persistence boundary without losing the run or selecting duplicate evidence; repeated idempotency keys return one run; cancellation and queue outage behave predictably; full matrix accounting is exact.

## 9. E6 — Evaluation, comparison, and policy

### T6.1 Deterministic evaluators

- Implement normalized/exact match, contains, regex, JSON parse/schema, and operational latency/cost metrics.
- Define normalization and Unicode semantics explicitly.
- Bound regex complexity/time and evidence size.

### T6.2 LLM judge

- Define pinned rubric, judge prompt/model/parser, structured result, and score range.
- Treat candidate output as delimited untrusted input and disable tools.
- Record judge inference attempts, usage, errors, and semantic identity.
- Calibrate with labeled fixtures and disagreement review.

### T6.3 Aggregation

- Aggregate per candidate/evaluator/slice with valid/error/skipped counts.
- Version aggregation semantics and input hashes.
- Ensure deterministic recomputation from selected evidence.

### T6.4 Baseline compatibility and pairing

- Pair by stable case key, evaluator semantic identity, and metric unit.
- Report missing/new/incompatible cases.
- Resolve zero denominators and missing values explicitly.

### T6.5 Comparison engine

- Compute absolute/relative deltas and direction-aware classifications.
- Produce aggregate and case comparison rows with deterministic ordering.
- Preserve improvements separately from regressions.

### T6.6 Policy engine

- Evaluate coverage/errors first, then critical, slice, and aggregate rules.
- Produce pass/fail/error and ordered per-rule decisions.
- Make evaluation pure, deterministic, and engine-versioned.
- Add comprehensive decision tables and property-based boundary tests.

### T6.7 Baseline promotion

- Implement eligible-run checks, expected revision, actor authorization, reason, history, and rollback-as-promotion.
- Block failed/errored/incomplete runs unless explicit approved override policy exists.

**Epic acceptance:** Golden fixtures reproduce identical decisions; threshold boundaries and higher/lower metrics are correct; missing evidence never passes implicitly; judge failures are errors rather than low scores; concurrent baseline promotions allow exactly one revision winner.

## 10. E7 — Reports and historical tracking

### T7.1 JSON result schema

- Version run summary, case results, comparison, decision, usage, and artifact manifest schemas.
- Keep large evidence paginated/referenced.
- Add backward-compatibility fixtures.

### T7.2 Safe HTML report

- Show provenance, gate/rules, aggregate/slice metrics, cost/latency, error coverage, regressions, improvements, and side-by-side case details.
- Escape all untrusted fields, add CSP, avoid third-party assets, and support large-run pagination or split artifacts.
- Record renderer/schema version and artifact hash.

### T7.3 Artifact publication

- Write temporary object, hash-verify, atomically publish, and manifest.
- Authorize signed downloads and audit restricted reads.
- Support idempotent regeneration without overwriting originals.

### T7.4 History APIs

- Add cursor-filtered run list, summaries, trends, baseline history, and case-result pagination.
- Optimize indexes/query plans against representative volume.

### T7.5 Retention

- Enforce project retention classes, legal hold, object deletion reconciliation, and tombstones.
- Test DB/object consistency and retry behavior.

**Epic acceptance:** Malicious model HTML/Markdown renders as inert text; JSON validates against the published schema; artifact interruption cannot expose a partial report; historical filters meet agreed latency at target volume.

## 11. E8 — GitHub Actions, CLI, Slack, and webhooks

### T8.1 CI client/CLI contract

- Submit, wait with bounded polling/backoff, show progress, download artifacts, and cancel explicitly.
- Define distinct process exit codes for pass, quality fail, system error/timeout, invalid request, and client error.
- Produce machine-readable outputs and concise job summaries.

### T8.2 Reusable GitHub Action/workflow

- Use secret inputs safely and least-privilege permissions.
- Attach JSON/HTML artifacts and expose report link.
- Demonstrate branch protection behavior for pass/fail/error.
- Decide later whether to add a GitHub App/check run.

### T8.3 Slack notifications

- Configure event/severity routing and test delivery.
- Redact raw content by default, deduplicate, retry, and dead-letter.
- Include gate, top blocking rules, commit/PR, cost/duration, and report URL.

### T8.4 Signed webhooks

- Implement event envelope/version, timestamped signature, replay window, event ID, retries, and per-subscription disable controls.
- Add consumer contract examples.

### T8.5 Dogfood workflow

- Run the system’s own curated evaluation fixture in CI.
- Include deliberate regression and provider-failure scenarios in a non-production test project.

**Epic acceptance:** A representative PR is blocked for a real quality regression and separately blocked as a system error during simulated provider outage; CI outputs distinguish both; duplicate Slack/webhook deliveries are safely identifiable.

## 12. E9 — Production hardening

### T9.1 Security review

- Perform STRIDE/OWASP threat modeling for API, reports, provider egress, webhooks, and artifacts.
- Test IDOR, token lifecycle, SSRF controls, report injection, judge prompt injection, secret leakage, and denial-of-wallet.
- Resolve all high findings and formally accept/track lower findings.

### T9.2 Reliability and load

- Load test target concurrency and 100k case-results/day.
- Soak test worker leases, Redis recovery, PostgreSQL pooling, object storage, and provider throttling.
- Verify backpressure and priority fairness under saturation.

### T9.3 Backup and disaster recovery

- Enable PostgreSQL PITR and object versioning/backup.
- Perform clean restore and hash reconciliation drill.
- Document RPO/RTO and degraded-mode decisions.

### T9.4 Observability and runbooks

- Build dashboards for SLOs, queue age, stuck states, provider errors, cost, reports, and delivery.
- Create runbooks for provider outage, DB/Redis/object-store failure, stuck runs, budget anomaly, migration failure, and compromised token.
- Exercise alerts in staging.

### T9.5 Release engineering

- Pin and scan images, generate SBOM, sign release artifacts, run migrations safely, and verify rollback/deploy health.
- Define compatibility and deprecation policy for API/report/event schemas.

### T9.6 Privacy and retention verification

- Verify data classification enforcement, provider allowlists, deletion, retention, legal hold, and restricted evidence audit.
- Document subprocessors and data flow if offered as a service.

**Epic acceptance:** Phase 6 criteria in roadmap pass, no open high-severity issue remains, restore/load/security exercises have evidence, and an on-call engineer can operate the service from runbooks.

## 13. E10 — Post-MVP extensions

### T10.1 Statistical reliability (P1)

- Repeated samples, seeds where supported, confidence intervals, paired bootstrap/permutation tests, minimum detectable effect, and flaky-case quarantine.
- Policy rules must distinguish statistical evidence from deterministic thresholds.

### T10.2 Provider expansion (P1)

- Add native providers only through contract suite.
- Support routing/fallback without invalidating provenance.

### T10.3 Human evaluation (P1)

- Blind review, assignment, rubric, disagreement resolution, adjudication, and inter-rater metrics.

### T10.4 Production drift (P1)

- Privacy-reviewed trace ingestion, sampling, scheduled runs, drift baselines, and alert tuning.

### T10.5 Plugin isolation (P2)

- Sandboxed or remote evaluator protocol with resource/network limits, signed packages, and capability declarations.

### T10.6 Enterprise scale (P2)

- SSO/SCIM, custom roles, RLS validation, per-tenant encryption keys, regional routing, quotas, partitions/read replicas, and possibly extracted execution service.

## 14. Cross-epic test matrix

| Concern | Minimum validation |
|---|---|
| Determinism | Canonical hash fixtures; policy decision replay; report stable ordering |
| Idempotency | Same key/same body; same key/different body; retry after response loss |
| Concurrency | Baseline promotion race; task lease race; duplicate outbox dispatch |
| Failure injection | Crash before/after call and persistence; dependency outages; malformed provider/judge response |
| Security | Cross-project access; secret canaries; XSS corpus; SSRF endpoints; webhook replay |
| Scale | Target matrix, history query, report size, queue backpressure, DB partitions |
| Compatibility | API/report/event schema fixtures; provider/evaluator adapter contract suites |
| Recovery | Migration rollback where supported; PITR/object restore; stuck-run reconciliation |
| Cost | Estimate/reserve/reconcile, unknown cost, duplicate attempt accounting, hard cap |
| Privacy | Classification block, retention deletion, legal hold, restricted-access audit |

## 15. Suggested ownership

- **AI platform:** provider gateway, evaluators, comparison semantics, judge calibration.
- **Backend/platform:** APIs, schema, orchestration, auth, artifact service.
- **DevOps/SRE:** containers, queue/database/object store, observability, CI, recovery, load.
- **Security:** threat model, token/secret handling, isolation, privacy controls.
- **Product/domain reviewers:** golden datasets, metric validity, threshold approval, beta labeling.

One technical owner should remain accountable for cross-component invariants and gate correctness.
