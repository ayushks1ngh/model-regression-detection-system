# Model Regression Detection System

Production foundation for an AI evaluation and regression-gating service. The product is designed to compare immutable **prompt versions**, **model versions**, and **agent versions** against approved baselines.

This repository currently implements **Milestones 1 through 3 only**: a runnable API/CLI skeleton, typed configuration, structured logging, health checks, a strict versioned evaluation-specification contract, canonical hashes, and a deterministic sequential fake-provider runner. OpenRouter, evaluator execution, persistence, workers, reports, and regression logic intentionally remain unimplemented.

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) for reproducible dependency management
- Docker (optional)

## Local setup

```bash
uv sync --extra dev
```

Run the API:

```bash
uv run uvicorn model_regression_detection.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
uv run mrds version
uv run mrds validate examples/evaluation.yaml
uv run mrds run-local examples/evaluation.yaml --responses examples/fake-responses.json
uv run mrds health --url http://127.0.0.1:8000
curl http://127.0.0.1:8000/health/live
```

## Quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov=model_regression_detection --cov-report=term-missing
```

## Docker

Build and run as a non-root user:

```bash
docker build -t mrds:m1 .
docker run --rm -p 8000:8000 mrds:m1
```

Then verify:

```bash
curl --fail http://127.0.0.1:8000/health/live
```

## Configuration

Settings use the `MRDS_` environment prefix.

| Variable | Default | Meaning |
|---|---|---|
| `MRDS_APP_NAME` | `model-regression-detection-system` | Service name |
| `MRDS_ENVIRONMENT` | `development` | `development`, `test`, `staging`, or `production` |
| `MRDS_LOG_LEVEL` | `INFO` | Python logging level |
| `MRDS_LOG_FORMAT` | `json` | `json` or `text` |
| `MRDS_HOST` | `0.0.0.0` | Server bind host |
| `MRDS_PORT` | `8000` | Server bind port |
| `MRDS_REQUEST_ID_HEADER` | `X-Request-ID` | Correlation header |

Invalid or unknown settings fail at startup. Do not put credentials in these general settings; later milestones will introduce explicit secret references.

## Current architecture

- `main.py`: application factory and composition root.
- `api/`: HTTP schemas, middleware, and routes.
- `config.py`: strict Pydantic settings.
- `logging.py`: structured standard-library logging.
- `cli.py`: operational CLI.
- `domain/versions.py`: shared immutable references for prompt, model, and agent versions.
- `specification/`: strict schema-v1 models, safe YAML/JSON loading, and canonical hashing.
- `providers/`: provider-neutral contracts and the deterministic fake adapter.
- `execution/`: sequential local rendering and provider result accounting.

See [`docs/milestones.md`](docs/milestones.md) for the implementation source of truth, [`docs/evaluation-specification.md`](docs/evaluation-specification.md) for the M2 contract, [`docs/local-runner.md`](docs/local-runner.md) for M3, and [`docs/architecture.md`](docs/architecture.md) for the target architecture. Target-state documentation is broader than the implemented milestone scope.
