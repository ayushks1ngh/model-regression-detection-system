# Product Requirements Document

## 1. Document control

- **Product:** AI Evaluation and Model Regression Detection System
- **Status:** Architecture proposal for review
- **Audience:** Product, AI/ML, platform, application, security, and DevOps engineers
- **Decision gate:** No implementation begins until this document and the linked architecture are approved
- **Related documents:** [Architecture](architecture.md), [Database](database.md), [Tasks](tasks.md), [Roadmap](roadmap.md)

## 2. Executive summary

The product is a CI/CD-style quality gate for LLM applications. It turns prompts, model configurations, golden datasets, evaluator definitions, and regression policies into immutable evaluation snapshots. A proposed prompt or model change is executed against a versioned dataset, compared with an explicitly selected baseline, and assigned a machine-readable gate result. Teams receive a durable HTML report, historical record, CI status, and optional Slack alert before deployment.

The system is not intended to prove that a model is universally correct. It provides repeatable evidence that a defined application behavior has not degraded beyond an agreed policy under a pinned evaluation configuration.

## 3. Problem statement

LLM application changes are difficult to review because outputs are probabilistic, quality is multidimensional, model APIs evolve, and manual spot checks are neither reproducible nor auditable. Teams need to answer:

1. What prompt, model, dataset, parameters, evaluators, and code revision were tested?
2. Did the candidate improve or regress against the approved baseline?
3. Which examples changed, and why did the gate pass or fail?
4. Can CI consume the result reliably without hiding provider failures as quality failures?
5. Can an engineer reproduce and audit the decision later?

## 4. Product principles

1. **Immutable evidence:** Published prompt versions, dataset versions, evaluator versions, run snapshots, raw outputs, and reports are append-only.
2. **Explicit baselines:** Baselines are promoted deliberately and never inferred from “the latest run.”
3. **Paired comparison:** Candidate and baseline are compared on matching case identities and compatible evaluation definitions.
4. **Fail closed for gates:** Missing required results, invalid configurations, or infrastructure failures cannot produce a passing deployment gate.
5. **Quality is not availability:** A model response failure is recorded separately from a low-quality response.
6. **Provider neutrality:** OpenRouter is the first provider integration behind a stable adapter contract.
7. **Reproducibility over convenience:** Every consequential setting is pinned in the run snapshot.
8. **Human-readable and machine-readable outcomes:** Reports explain decisions; APIs and process exit codes automate them.
9. **Cost and privacy are first-class:** Token use, spend, redaction, retention, and data classification are visible controls.

## 5. Users and jobs to be done

### 5.1 Personas

- **AI application engineer:** Versions prompts, runs candidate evaluations, diagnoses failed cases, and proposes baselines.
- **ML/AI platform engineer:** Defines evaluators and policies, manages providers, controls cost, and maintains reliability.
- **Release/DevOps engineer:** Adds the evaluation gate to GitHub Actions and consumes deterministic status outputs.
- **Reviewer or product owner:** Reads reports, reviews qualitative changes, and approves baseline promotion.
- **Security/compliance operator:** Audits access, data retention, secret use, and historical deployment evidence.

### 5.2 Primary user journey

1. A team publishes a candidate prompt version or changes a model configuration.
2. GitHub Actions submits an evaluation request containing the project, candidate configuration, dataset version, policy, baseline selector, and source revision.
3. The service validates and freezes an immutable run snapshot.
4. Workers render test cases and call one or more configured models through OpenRouter.
5. Evaluators score outputs; the comparison engine pairs candidate and baseline evidence.
6. The regression policy produces `pass`, `fail`, or `error` with explicit reasons.
7. The service publishes JSON summaries and a self-contained HTML diff report.
8. CI exits successfully only for `pass`; Slack receives a concise result and report link.
9. An authorized user may promote the successful run to a named baseline.

## 6. Goals and success metrics

### 6.1 Product goals

- Make prompt/model changes reviewable before deployment.
- Detect meaningful case-level and aggregate regressions.
- Preserve an auditable history of what was evaluated and why it passed or failed.
- Offer a low-friction GitHub Actions integration suitable for branch protection.
- Allow additional model providers and evaluators without changing orchestration semantics.

### 6.2 Initial service-level and product indicators

| Indicator | Initial target |
|---|---:|
| Valid evaluation requests accepted | >= 99.5% monthly, excluding provider outages |
| Final gate consistency | 100% for identical persisted evidence and policy version |
| Report generation success after completed scoring | >= 99.9% |
| CI-visible result after run completion | <= 30 seconds |
| Run traceability | 100% include immutable config, source revision, and actor |
| Provider cost attribution | >= 99% of successful calls have token/cost metadata when supplied |
| Duplicate execution due to retries | < 0.1%, with duplicates detected and excluded |
| MVP scale target | 100 concurrent model calls and 100k case-results/day per deployment |

Quality-detection precision and recall cannot be set globally before real labeled regressions exist. During beta, teams must label false positives and missed regressions; those labels establish project-specific policy targets.

## 7. Scope

### 7.1 MVP / first production release

- Logical organizations/workspaces and projects, even if initially deployed single-tenant.
- Prompt templates with immutable versions and rendering-variable declarations.
- Golden datasets with drafts, validation, immutable published versions, cases, expected outputs, metadata, tags, and optional evaluator-specific assertions.
- Model configurations with provider, provider model identifier, generation parameters, and pinned aliases where possible.
- OpenRouter provider with timeout, retry, rate-limit, usage, and normalized error handling.
- Evaluation suites linking dataset versions, prompt versions, model configurations, evaluators, and regression policy versions.
- Deterministic evaluators: exact/normalized match, contains/regex, JSON validity/schema, and latency/cost checks.
- Rubric-based LLM-as-judge evaluator with a separately pinned judge model, rubric, and prompt version.
- Asynchronous multi-model execution, cancellation, bounded retries, idempotency, and resumable orchestration.
- Explicit baseline channels such as `main`, `staging`, or `production`.
- Aggregate and case-level comparisons with absolute thresholds, relative deltas, critical-case rules, and minimum coverage.
- Historical run and comparison tracking.
- Self-contained HTML and JSON reports.
- Slack webhook notification and GitHub Actions-friendly CLI/API behavior.
- Docker images and a local/production Compose reference topology.
- Authentication, project-scoped authorization, audit events, structured logs, metrics, and health endpoints.

### 7.2 Later scope

- Native provider adapters beyond OpenRouter.
- Human review queues and inter-rater workflows.
- Semantic similarity/embedding evaluators and domain-specific plugins.
- Repeated sampling, confidence intervals, significance tests, and sequential evaluation.
- Web dashboard for authoring and analytics; MVP may be API/CLI/report centered.
- Scheduled drift evaluation against sampled production traffic.
- Dataset curation from production traces with PII review.
- Enterprise SSO, SCIM, advanced RBAC, regional data residency, and managed multi-tenancy.
- Distributed workflow engines and autoscaling across regions.

### 7.3 Non-goals for MVP

- Training or fine-tuning models.
- Hosting model inference directly.
- Replacing application observability or production safety controls.
- Automatically declaring subjective output “correct” without evaluator policy.
- Scraping production data without explicit ingestion and privacy controls.
- A general-purpose prompt IDE or full experiment-tracking platform.

## 8. Functional requirements

### FR-1 Project and access management

- Resources are scoped to a workspace and project.
- API credentials and users have explicit roles: viewer, runner, editor, approver, and administrator.
- All mutations, baseline promotions, cancellations, and secret-configuration changes create audit events.
- Cross-project resource access is denied by default.

### FR-2 Prompt versioning

- A prompt has stable identity, name, description, input contract, and tags.
- Published versions are immutable and carry content hash, author, timestamp, changelog, rendering syntax version, and optional Git metadata.
- Prompt rendering validates missing and unexpected variables before any provider call.
- Secrets are not valid prompt variables and must never be interpolated from stored credentials.

### FR-3 Golden dataset management

- A dataset is edited as a draft and published as an immutable version.
- Each case has a stable logical key, inputs, optional expected output, metadata, tags, criticality, and evaluator assertions.
- Publishing validates unique case keys, variable compatibility, schema correctness, size limits, and sensitive-data classification.
- A published version records ordered case membership and content hashes so later edits cannot alter historical runs.
- Import/export supports a documented JSONL contract in a later MVP subphase; malformed rows produce row-level validation errors.

### FR-4 Models and providers

- Model configurations pin provider adapter, provider model ID, generation parameters, timeout, retry policy, and optional routing constraints.
- OpenRouter credentials are referenced by secret identifier and never returned by the API or persisted in snapshots.
- Provider responses normalize output text/structured content, finish reason, latency, usage, cost when available, provider request ID, and error classification.
- Provider alias drift must be visible. For strict baselines, resolved model/revision metadata is retained when exposed by the provider.

### FR-5 Evaluation suites and evaluator versioning

- A suite is a reusable definition whose published versions are immutable.
- The suite identifies dataset version, candidate prompt/config slots, evaluator versions, weights, required evaluators, concurrency limits, and policy version.
- Evaluators return normalized status, score where applicable, label, explanation, and evidence.
- LLM judges are isolated from candidate model settings and store judge prompt/rubric/model versions.
- Evaluator failures remain distinguishable from candidate quality failures.

### FR-6 Run orchestration

- A run request resolves every mutable selector into an immutable snapshot before queueing.
- Runs support one or more candidate model configurations and an optional baseline comparison.
- States are monotonic: `created`, `validating`, `queued`, `running`, `evaluating`, `comparing`, `reporting`, then a terminal state.
- Terminal execution states are `completed`, `failed`, `cancelled`, and `expired`; gate outcome is separately `pass`, `fail`, `error`, or `not_evaluated`.
- Retries are bounded and classified; permanent errors are not retried.
- The same idempotency key and equivalent request returns the original run; conflicting payloads are rejected.
- Cancellation stops new work, attempts to cancel in-flight calls, and preserves partial evidence.

### FR-7 Baselines and comparison

- A baseline is a named project channel pointing to one eligible completed run or immutable result snapshot.
- Promotion requires approver permission, reason, audit event, and optimistic concurrency.
- Comparison compatibility requires matching logical cases and evaluator semantics; missing cases are reported and policy-controlled.
- The engine computes baseline value, candidate value, absolute delta, relative delta where defined, and direction-aware classification.
- Improvements do not silently offset critical regressions unless a policy explicitly permits weighted aggregation.

### FR-8 Regression policies

A versioned policy can define:

- Required run coverage and maximum provider/evaluator error rate.
- Per-metric direction (`higher_is_better`, `lower_is_better`, or categorical).
- Absolute floors/ceilings.
- Maximum absolute and percentage regression from baseline.
- Maximum number/fraction of regressed cases.
- Zero-tolerance critical cases or tags.
- Model-specific and dataset-slice thresholds.
- Minimum sample count and behavior when no compatible baseline exists.
- Warning-only rules versus blocking rules.

Every final gate decision includes rule IDs, measured values, thresholds, and affected cases.

### FR-9 Reports and history

- Reports show provenance, configuration, gate summary, rule decisions, aggregate metrics, cost/latency, failures, improvements, regressions, and side-by-side case diffs.
- HTML reports are self-contained or use signed artifact links, escape model-generated content, and enforce a restrictive content security policy.
- JSON reports follow a versioned schema for CI and downstream systems.
- Historical queries filter by project, suite, branch, commit, prompt, model, dataset, status, gate outcome, and time.
- Raw evidence retention is configurable independently from aggregate history.

### FR-10 Integrations

- GitHub Actions can submit a run, poll or wait, download artifacts, post a check/summary, and fail the job based on gate outcome.
- The integration distinguishes gate failure from system failure using output fields and documented process exit codes.
- Slack notifications are configurable by event and severity, deduplicated, retried, and contain no raw sensitive prompts/outputs by default.
- Webhooks are signed, retryable, versioned, and delivered at least once with event IDs for consumer deduplication.

### FR-11 Operations

- Deployment is containerized with separate API, worker, and report-serving responsibilities; local development may combine roles.
- Readiness checks verify required dependencies; liveness checks do not depend on third-party providers.
- Structured logs and metrics correlate workspace, project, run, task, case, model, evaluator, and provider request IDs without logging secrets.
- Operators can set global/project budgets, concurrency, retention, timeout, and rate limits.

## 9. Regression semantics

### 9.1 Units of comparison

Metrics exist at four levels: provider attempt, case result, dataset slice, and whole run. Gate rules must state their level. Candidate-versus-baseline comparison is paired by stable case key and evaluator version/semantic identity, not by row position.

### 9.2 Classification

- **Improved:** Delta exceeds the configured improvement threshold in the desirable direction.
- **Unchanged:** Delta remains within tolerance.
- **Regressed:** Delta exceeds allowed tolerance in the undesirable direction.
- **Incomparable:** Evidence or semantics are incompatible or absent.
- **Errored:** Execution or evaluator did not produce valid evidence.

### 9.3 Default gate precedence

1. Invalid snapshot or infrastructure-wide failure -> `error`.
2. Coverage below minimum or required evidence missing -> `error` unless policy explicitly marks it blocking `fail`.
3. Any blocking critical-case violation -> `fail`.
4. Any blocking aggregate/slice rule violation -> `fail`.
5. Otherwise -> `pass`, with warnings preserved.

A gate `fail` means valid evidence found unacceptable quality. A gate `error` means the system could not establish quality. CI blocks on both but reports them differently.

## 10. Conceptual API and integration requirements

The canonical API is versioned REST/JSON under `/api/v1`; an internal service layer must not depend on HTTP so a CLI, scheduler, or future event API can reuse it.

| Resource | Required operations |
|---|---|
| Projects | create, retrieve, list, update metadata, archive |
| Prompts | create prompt; create/list/get/publish versions |
| Datasets | create draft; upsert/import/validate cases; publish/list/get versions |
| Model configurations | create, validate provider access, list, archive |
| Evaluators/policies/suites | create draft, validate, publish immutable version, retrieve |
| Runs | submit, retrieve, list/filter, cancel, retry eligible work, stream/poll status |
| Results/reports | summary, case pagination, comparisons, signed artifact download |
| Baselines | retrieve channel, promote with expected revision, list history |
| Integrations | configure/test Slack; issue/revoke project tokens; webhook subscriptions |

Cross-cutting API behavior:

- Bearer authentication; project-scoped service tokens for CI.
- `Idempotency-Key` required for run submission and recommended for other creates.
- Cursor pagination for unbounded collections.
- RFC-style problem details with stable error codes and field-level validation issues.
- UTC ISO-8601 timestamps, opaque identifiers, explicit schema versions.
- `ETag`/revision preconditions for mutable pointers such as baselines.
- Rate-limit headers and correlation/request IDs.
- No secrets or full raw outputs in list endpoints.

Detailed contracts and Pydantic-style conceptual models are defined in [architecture.md](architecture.md) and [database.md](database.md).

## 11. Security, privacy, and compliance requirements

- Secrets reside in environment/secret manager references, are encrypted in transit and at rest, masked in logs, and excluded from reports.
- Stored prompts and model outputs are untrusted content. Reports must encode output and must never execute embedded HTML, Markdown scripts, or URLs.
- Access checks are enforced at every resource boundary, including artifact downloads and worker tasks.
- Dataset classification supports at least `public`, `internal`, `confidential`, and `restricted`; restricted data may prohibit external providers.
- Configurable retention and deletion workflows cover raw provider payloads, outputs, artifacts, and audit-preserving tombstones.
- Provider requests disclose the selected data handling route; a project allowlist controls providers/models.
- Webhooks use per-subscription signing secrets and replay windows.
- Supply-chain scanning, pinned dependencies/images, non-root containers, and migration backups are release requirements.
- Audit records are append-only at application level and include actor, action, target, request correlation, time, and non-secret change summary.

## 12. Assumptions and decisions requiring approval

### 12.1 Working assumptions

- Python is the implementation language; FastAPI/Pydantic concepts suit contract validation.
- PostgreSQL is authoritative storage, Redis is the initial queue/cache coordinator, and S3-compatible object storage holds reports/large payloads.
- OpenRouter is the initial inference route and exposes usage/cost inconsistently across underlying models.
- Initial deployments can be logically multi-tenant while operationally single-region.
- Golden datasets fit into batch evaluation; streaming conversations and agent tool traces are later extensions.
- A model response may remain nondeterministic even with temperature zero, so strict byte-for-byte reproducibility is not promised.

### 12.2 Approval questions

1. Is MVP API/CLI/report-first acceptable, with a full web dashboard deferred?
2. Is explicit human baseline promotion required for protected channels, or may CI auto-promote after merge?
3. What customer data classifications may be sent to OpenRouter?
4. What are the initial monthly budget and maximum concurrent-call defaults?
5. Is a rubric-based LLM judge required in MVP, given cost and judge instability?
6. Must GitHub integration use a GitHub App/check-run API initially, or is a reusable Action plus job summary sufficient?
7. What raw output retention period is acceptable?
8. Is logical multi-tenancy enough for v1, or is hard tenant isolation a launch requirement?

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Nondeterministic outputs cause flaky gates | Developer distrust | Tolerance bands, fixed configs, optional repeated sampling, quarantine flaky cases, show uncertainty |
| LLM judge bias or drift | Incorrect gates | Pin judge config/rubric, calibration set, judge version comparisons, deterministic checks where possible |
| Moving provider aliases | Irreproducible baselines | Prefer pinned IDs, retain resolved metadata, warn or block incompatible comparisons |
| Dataset overfitting | Good eval score, poor production behavior | Holdout suites, slice coverage, periodic refresh, production-feedback curation |
| API rate limits/outages | Delayed or errored CI | Backoff with jitter, concurrency governors, provider circuit breaker, explicit system outcome |
| Cost spikes | Budget breach | Preflight estimate, hard budgets, token caps, cancellation, usage reconciliation |
| Sensitive data leakage | Security/compliance incident | Classification, provider allowlists, redaction, minimal retention, no payload logging |
| Baseline misuse | False pass/fail | Explicit channels, compatibility checks, promotion audit and concurrency control |
| Queue duplication/worker crash | Double spend or corrupt aggregates | Idempotent task leases, attempt records, unique constraints, reconciliation sweeper |
| Report injection | Credential/session compromise | Escaping, sanitization, CSP, artifact access control, no active model content |
| Metric gaming | Misleading aggregate score | Critical cases, per-slice rules, no implicit offset, transparent rule evidence |
| Schema growth from raw JSON | Slow queries/storage bloat | Normalize query-critical fields, object storage for large bodies, partition/retention plan |

## 14. Release readiness definition

A release phase is complete only when its acceptance criteria in [roadmap.md](roadmap.md) pass, threat-model findings rated high are resolved, migration rollback/restore is exercised, API and report schemas are versioned, operational dashboards and runbooks exist, and a representative GitHub Actions workflow demonstrates both a quality regression and a provider outage being blocked for the correct reason.

## 15. gstack reference

The planning process borrowed gstack’s separation of product challenge, engineering review, test planning, and explicit ship gates. That framing helped force assumptions into this PRD, separate quality failures from system failures, add acceptance gates before implementation, and treat documentation as part of release readiness. No gstack code was copied or installed; its public workflow was used only as a planning reference: <https://github.com/garrytan/gstack>.

Content derived from the reference was rephrased for licensing compliance.
