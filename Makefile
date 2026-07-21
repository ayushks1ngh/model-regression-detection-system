.PHONY: install lint typecheck test coverage security-scan clean

install:
	uv sync --dev --all-extras

lint:
	ruff check src/ tests/

typecheck:
	mypy src/

test:
	pytest tests/ -x -q

coverage:
	pytest tests/ -x --cov=model_regression_detection --cov-report=term-missing

security-scan:
	bandit -r src/ -x tests/
	pip-audit

clean:
	rm -rf .coverage htmlcov/ .mypy_cache/ .pytest_cache/ __pycache__/
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
