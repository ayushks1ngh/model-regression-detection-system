.PHONY: install lint format typecheck test coverage security-scan clean all check

all: format lint typecheck test

check: lint typecheck test

install:
	uv sync --extra dev --extra prometheus

format:
	uv run ruff format .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest -x -q

coverage:
	uv run pytest --cov=model_regression_detection --cov-report=term-missing

security-scan:
	uv run bandit -r src/ -x tests/ -c pyproject.toml
	uv run pip-audit

clean:
	rm -rf .coverage htmlcov/ .mypy_cache/ .pytest_cache/ __pycache__/ test.db
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
