.PHONY: test lint typecheck check

test:
	pytest -q --cov=proto_client --cov-report=term-missing --cov-report=xml:coverage.xml --cov-branch --cov-fail-under=80

lint:
	ruff check . && ruff format --check .

typecheck:
	mypy proto_client/

check: lint typecheck test
