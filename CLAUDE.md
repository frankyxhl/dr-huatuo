# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Huatuo (华佗) is a Python code quality analysis toolkit. It orchestrates multiple static analysis tools (ruff, radon, bandit, mypy, pylint) to produce unified quality reports with scoring and grading. Named after the legendary Chinese physician — it diagnoses code health.

## Commands

```bash
# Activate venv (Python 3.12)
source .venv/bin/activate

# Analyze a single file
python code_analyzer.py <file_or_dir>

# Generate project report (terminal, json, markdown, or html)
python code_reporter.py <project_path> -f terminal
python code_reporter.py <project_path> -f html -o report.html
python code_reporter.py <project_path> -f json -o report.json
python code_reporter.py <project_path> -f markdown -o report.md

# Exclude directories
python code_reporter.py <path> -e .venv __pycache__ .git

# Run the example code (intentionally flawed, for demo purposes)
python code_analyzer.py example_code.py

# Makefile targets (work without venv activation)
make test          # Run all tests (pytest)
make lint          # Lint source and tests (ruff check)
make fmt           # Auto-format source and tests (ruff format)
make check         # Run lint, then test (fails if either fails)
```

### Required Tools (in venv)

All analysis tools must be available on PATH: `ruff`, `radon`, `bandit`, `mypy`, `pylint`. Install with:

```bash
pip install ruff radon bandit mypy pylint
```

Additional venv dependencies: `rich` (terminal rendering), `pytest`, `pytest-cov`, `coverage`.

## Architecture

Two main modules with distinct roles:

- **`code_analyzer.py`** — Lightweight single-file analyzer. `CodeAnalyzer` class runs each tool via subprocess, collects results into a `CodeMetrics` dataclass, computes a 0-100 score. Entry point: `review_code(path)`.

- **`code_reporter.py`** — Full project analyzer with rich output. Contains its own `CodeAnalyzer` (enhanced version with AST-based complexity breakdown), `ProjectReport`/`FileMetrics` dataclasses, and `ReportRenderer` that outputs to terminal (via `rich`), JSON, Markdown, or HTML (with Chart.js). Entry point: `generate_report(path, format, exclude, output_file)`.

- **`example_code.py`** — Intentionally flawed sample code for demo/testing (eval usage, high complexity, hardcoded secrets, duplicate functions).

### Scoring System

Score starts at 100, deductions: ruff violations (-2 each, max -30), complexity >10 (-3-5 per unit, max -20-25), bandit HIGH (-15 each, max -30), bandit MEDIUM (-5 each, max -15), mypy errors (-1 each, max -10). Grades: A (90+), B (80+), C (70+), D (60+), F (<60).

### Key Pattern

Both modules shell out to analysis tools via `subprocess.run()` with JSON output flags, parse the JSON results, and aggregate into dataclasses. The `code_reporter.py` version additionally uses Python's `ast` module to provide per-function complexity breakdowns showing exact branch points.

## Code Language Policy

All code must be written in English: comments, docstrings, variable names, log messages, error messages, and user-facing strings. See HUA-2101-ADR for rationale.

## Alfred Document System

This project uses the Alfred document system (prefix: `HUA`). Documents live in `rules/`.

### Session Start (MANDATORY)

Every session must begin by running `af guide` and following the decision tree to route the task:

```bash
af guide         # Read the decision tree, determine which SOP to follow
af list          # See all project documents
```

Route the task per COR-1103 before doing any work. Declare the active SOP (COR-1402) before starting.

### Common af Commands

```bash
af create sop --prefix HUA --area 21 --title "My SOP"
af create adr --prefix HUA --area 21 --title "My Decision"
af create chg --prefix HUA --area 21 --title "My Change"
af create prp --prefix HUA --area 21 --title "My Proposal"
af index        # Regenerate document index
af search <pattern>
af validate
```
