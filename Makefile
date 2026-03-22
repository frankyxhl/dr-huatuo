VENV := .venv/bin

.PHONY: test lint fmt check

test:
	$(VENV)/python -m pytest tests/ -v

lint:
	$(VENV)/ruff check src/dr_huatuo/*.py example_code.py tests/

fmt:
	$(VENV)/ruff format src/dr_huatuo/*.py example_code.py tests/

check: lint test
