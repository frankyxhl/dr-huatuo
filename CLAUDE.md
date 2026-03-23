# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Huatuo (华佗) is a Python code quality analysis toolkit. It orchestrates multiple static analysis tools (ruff, radon, bandit, mypy, pylint) to produce unified quality reports with scoring and grading. Named after the legendary Chinese physician — it diagnoses code health.

## Commands

```bash
# Activate venv (Python 3.13)
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

# Run a single test file or specific test
.venv/bin/pytest tests/test_analyzer_scoring.py -v
.venv/bin/pytest tests/test_analyzer_scoring.py::TestCalculateScore::test_all_zeros_score_100 -v

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

### Plugin System

- **`analyzers/base.py`** — `LanguageAnalyzer` protocol + `BaseAnalyzer` base class + `ToolNotFoundError`
- **`analyzers/python.py`** — `PythonAnalyzer` wraps `CodeAnalyzer` + Layer 2 metrics (radon MI, complexipy, AST). Registered for `.py` files.
- **`analyzers/__init__.py`** — Registry with `register()`, `create_analyzer()`, auto-registers `PythonAnalyzer`

### Core Modules

- **`cli.py`** — Unified CLI (`ht check`, `ht report`, `ht version`). Uses `create_analyzer()` from registry.
- **`code_analyzer.py`** — `CodeAnalyzer` class runs ruff/radon/bandit/mypy/pylint via subprocess, returns `CodeMetrics` dataclass. Legacy module, wrapped by `PythonAnalyzer`.
- **`code_reporter.py`** — Full project reports. Own `CodeAnalyzer` + `FileMetrics` + `ReportRenderer` (terminal/HTML/JSON/Markdown). Entry point: `generate_report()`.
- **`quality_profile.py`** — 5-dimension quality profile (Maintainability, Complexity, Code Style, Documentation, Security). Language-agnostic.
- **`example_code.py`** — Intentionally flawed sample code for demo/testing.

### Field Names (Generic)

Dataclasses use generic field names (HUA-2129 Phase 3):
`lint_violations`, `linter_score`, `security_high`, `security_medium`, `type_errors`.
Old names (`ruff_violations`, `pylint_score`, `bandit_high`, `bandit_medium`, `mypy_errors`) supported via `__getattr__` and `__init__` compat wrappers for backward compat with research modules.

### Scoring System

Unified across both analyzers (HUA-2130-ADR): score starts at 100, deductions: lint violations (-2 each, max -30), complexity >10 (`(cc-10)*5`, max -20), security HIGH (-15 each, max -30), security MEDIUM (-5 each, max -15), type errors (-1 each, max -10). Floor at 0. Grades: A (90+), B (80+), C (70+), D (60+), F (<60). Labels: `"A (Excellent)"`, `"F (Fail)"`.

### Testing Pattern

Unit tests avoid subprocess calls by instantiating `CodeAnalyzer` via `object.__new__(CodeAnalyzer)` (bypassing `__init__`). See `tests/conftest.py` for shared fixtures. `PythonAnalyzer` tests in `tests/test_python_analyzer.py`. Registry tests in `tests/test_analyzer_registry.py`.

### Reference Document

`tools_integration_reference.md` — technical reference for each tool's CLI flags, JSON output schema, and Python integration examples. Written in Chinese (predates the Code Language Policy).

## Code Language Policy

All code must be written in English: comments, docstrings, variable names, log messages, error messages, and user-facing strings. See HUA-2101-ADR for rationale.

## Alfred Document System

This project uses the Alfred document system (prefix: `HUA`). Documents live in `rules/`.

### Workflow (Full — Option C)

At session start:
1. `af guide --root /Users/frank/Projects/huatuo` — see routing (PKG → USR → PRJ layers)

Before every task:
2. From the decision tree, identify which SOPs apply to this task
3. `af plan <SOP_IDs>` — generate step-by-step workflow checklist
4. Follow each step, declaring active SOP at transitions (COR-1402)
5. Do not commit code without completing review steps
6. At task end, use the plan output as completion checklist

`af guide` = once per session (routing context).
`af plan` = before EVERY task (checklist from SOPs).

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
