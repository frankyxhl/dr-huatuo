VENV := .venv/bin

.PHONY: test lint fmt check

test:
	$(VENV)/python -m pytest tests/ -v

lint:
	$(VENV)/ruff check code_analyzer.py code_reporter.py example_code.py tests/

fmt:
	$(VENV)/ruff format code_analyzer.py code_reporter.py example_code.py tests/

check: lint test
