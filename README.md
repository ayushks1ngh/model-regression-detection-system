# Model Regression Detection System (MRDS)

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://docs.astral.sh/ruff/)

A production-grade AI evaluation and regression-gating service. MRDS compares immutable **prompt versions**, **model versions**, and **agent versions** against approved baselines, providing deterministic pass/fail/error gates for CI/CD pipelines.

## What It Does

- **Evaluates AI outputs** against golden-case datasets using six built-in deterministic evaluators
- **Gates deployments** with configurable policy rules (pass rate, latency, cost, critical cases)
- **Tracks baselines** so you know when a model or prompt change causes a regression
- **Integrates into CI** via CLI exit codes and a reusable GitHub Actions workflow
- **Scales with workers** that claim and execute evaluation runs from a PostgreSQL queue

## Quick Start

### Prerequisites

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) for reproducible dependency management

### Install and Run Locally

```bash
# Clone and install
git clone https://github.com/yourorg/model-regression-detection-system.git
cd model-regression-detection-system
uv sync --extra dev

# Validate an evaluation specification
uv run mrds validate examples/evaluation.yaml

# Run evaluation locally with deterministic fake responses
uv run mrds run-local examples/evaluation.yaml --responses examples/fake-responses.json

# Generate a JSON report
uv run mrds run-local examples/evaluation.yaml \
  --responses examples/fake-responses.json \
  --report report.json
```

### Run the API Server

```bash
uv run uvicorn model_regression_detection.main:app --host 127.0.0.1 --port 8000
```

Then:
```bash
curl http://127.0.0.1:8000/health/live
uv run mrds health --url http://127.0.0.1:8000
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  CLI / CI   │────▶│   FastAPI    │────▶│   PostgreSQL    │
│  (mrds)     │     │   (API)      │     │   (persistence) │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                    ┌──────────────┐               │
                    │   Worker     │◀──────────────┘
                    │ (poll/exec)  │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Provider    │
                    │ (OpenRouter) │
                    └──────────────┘
```

### Core Components

| Component | Description |
|---|---|
| `specification/` | Strict schema-v1 models, YAML/JSON loading, canonical hashing |
| `providers/` | Provider-neutral contracts, fake adapter, OpenRouter adapter |
| `execution/` | Sequential runner, per-run limits, cancellation tokens |
| `evaluators/` | Six built-in deterministic assertions with bounded evidence |
| `policy/` | Deterministic aggregation, fixed pass/fail/error gate, baseline comparison |
| `reporting/` | Versioned JSON and HTML report generation |
| `persistence/` | Async PostgreSQL schema, migrations, run repository |
| `workers/` | Durable worker with retry/backoff, heartbeat lease renewal |
| `api/` | Run submission, status, cancellation, baselines, token auth |
| `notifications/` | Slack webhook integration for terminal run outcomes |

## Docker Deployment

```bash
# Build and run the full stack
docker compose up -d

# Or build individually
docker build -t mrds:latest .
docker run --rm -p 8000:8000 mrds:latest
```

The docker-compose setup includes:
- **PostgreSQL 17** with persistent volume
- **API server** with health checks and auto-migration
- **Worker** with configurable provider (fake or OpenRouter)

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MRDS_APP_NAME` | `model-regression-detection-system` | Service name |
| `MRDS_ENVIRONMENT` | `development` | `development` / `test` / `staging` / `production` |
| `MRDS_LOG_LEVEL` | `INFO` | Python logging level |
| `MRDS_LOG_FORMAT` | `json` | `json` or `text` |
| `MRDS_HOST` | `0.0.0.0` | Server bind host |
| `MRDS_PORT` | `8000` | Server bind port |
| `MRDS_DATABASE_URL` | — | PostgreSQL URL (enables persistence) |
| `MRDS_MAX_REQUEST_BODY_SIZE` | `10000000` | Max request body in bytes |
| `MRDS_OPENROUTER_API_KEY` | — | Required for worker (live mode) |
| `MRDS_WORKER_FAKE_PROVIDER` | — | Set to `1` for local testing |

Invalid or unknown settings fail at startup.

## CI/CD Integration

### Exit Codes

| Code | Meaning | CI Status |
|---|---|---|
| 0 | All policy rules passed | ✅ Green |
| 1 | Regression detected | ❌ Red |
| 2 | System/evaluation error | ❌ Red |
| 3 | Timeout | ❌ Red |

### GitHub Actions (Reusable Workflow)

```yaml
jobs:
  evaluate:
    uses: yourorg/model-regression-detection-system/.github/workflows/evaluate.yml@main
    with:
      spec-path: specs/my-eval.yaml
      project-id: my-project
      api-url: https://mrds.example.com
```

### CLI Workflow

```bash
# Submit and wait for the gate decision
RUN_ID=$(mrds submit specs/eval.yaml --project-id my-project --url https://mrds.example.com)
mrds wait "$RUN_ID" --url https://mrds.example.com --timeout-seconds 600
# Exit code reflects the gate decision
```

## Evaluation Specification

Specifications are YAML/JSON files that define what to evaluate:

```yaml
schema_version: "1"
suite: "my-smoke-test"
prompt:
  target: { kind: prompt, name: customer-support, version: "2.1" }
  messages:
    - role: system
      content: "You are a helpful customer support agent."
    - role: user
      content: "{question}"
model:
  target: { kind: model, name: gpt-4o, version: "2024-11-20" }
  model_id: "openai/gpt-4o"
  temperature: 0.0
evaluators:
  - name: contains_keyword
    type: contains
    expected: "refund"
    required: true
cases:
  - key: refund-question
    inputs: { question: "What is your refund policy?" }
    critical: true
policy:
  minimum_pass_rate: 0.9
  maximum_error_rate: 0.1
  critical_cases_must_pass: true
```

See [`docs/evaluation-specification.md`](docs/evaluation-specification.md) for the full schema reference.

## Development

### Quality Checks

```bash
make check          # lint + typecheck + test
make coverage       # pytest with coverage report
make security-scan  # bandit + pip-audit
```

Or individually:
```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=model_regression_detection --cov-report=term-missing
```

### Project Structure

```
src/model_regression_detection/
├── __init__.py          # Version
├── main.py              # FastAPI app factory
├── config.py            # Pydantic settings
├── logging.py           # Structured logging
├── cli.py               # Typer CLI
├── api/                 # HTTP layer
├── domain/              # Shared value objects
├── specification/       # Eval spec schema & loader
├── providers/           # LLM provider adapters
├── execution/           # Runner & limits
├── evaluators/          # Built-in assertions
├── policy/              # Aggregation & gate engine
├── reporting/           # JSON & HTML reports
├── persistence/         # PostgreSQL ORM & repository
├── workers/             # Background execution
└── notifications/       # Slack integration
```

## Documentation

| Document | Description |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Target architecture overview |
| [`docs/milestones.md`](docs/milestones.md) | Implementation milestones |
| [`docs/evaluation-specification.md`](docs/evaluation-specification.md) | Spec schema reference |
| [`docs/local-runner.md`](docs/local-runner.md) | Local execution details |
| [`docs/evaluators.md`](docs/evaluators.md) | Built-in evaluator reference |
| [`docs/policy.md`](docs/policy.md) | Policy engine rules |
| [`docs/json-report.md`](docs/json-report.md) | Report format |
| [`docs/persistence.md`](docs/persistence.md) | Database schema |
| [`docs/run-submission-api.md`](docs/run-submission-api.md) | API reference |
| [`docs/worker.md`](docs/worker.md) | Worker operations |
| [`docs/limits.md`](docs/limits.md) | Execution limits |
| [`docs/openrouter.md`](docs/openrouter.md) | OpenRouter provider |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup, code quality requirements, and production runbooks.

## License

[MIT](LICENSE)
