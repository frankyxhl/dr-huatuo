# PRP-2100: Add Test Infrastructure

**Applies to:** HUA project
**Last updated:** 2026-03-20
**Last reviewed:** 2026-03-20
**Status:** Implemented
**Related:** —
**Reviewed by:** Codex (9.5/10 R4), Gemini (10.0/10 R3)

---

## What Is It?

Add a Makefile-based test infrastructure to the huatuo project. This includes a `pyproject.toml` for pytest configuration, a `tests/` directory with unit tests covering scoring logic, grade assignment, and report rendering (JSON/Markdown), and Makefile targets for running tests and linting.

---

## Problem

The project currently has no tests. pytest and pytest-cov are installed in the venv but there is no test directory, no pytest configuration, and no standardized way to run tests. This means:

- No way to verify that changes to scoring logic or tool parsing don't break existing behavior
- No way to catch regressions when modifying the dual `CodeAnalyzer` classes (both `code_analyzer.py` and `code_reporter.py` have their own `CodeAnalyzer` with divergent scoring)
- Contributors must manually verify every change
- No linting or formatting entry point for the project's own code

---

## Scope

**In scope (v1):**
- `pyproject.toml` with pytest and ruff configuration
- Makefile with `test`, `lint`, `fmt`, `check` targets
- `tests/` directory with `conftest.py` and initial test modules
- Unit tests for scoring logic (`_calculate_score`, `_get_grade`) in both analyzers, including boundary and edge cases
- Unit tests for `ReportRenderer.render_json` and `ReportRenderer.render_markdown` output structure
- Unit tests for edge cases: zero-value metrics, empty file lists, empty project reports
- Update `CLAUDE.md` to document `make test`, `make lint`, `make check` commands

**Out of scope (v1):**
- Integration tests requiring external tools (ruff, radon, bandit, mypy) — subprocess-dependent tests are deferred to a future PRP that defines a mocking or fixture strategy
- HTML rendering tests — `render_html` produces 600+ lines of inline HTML/JS with Chart.js; visual verification is more appropriate than string assertions for v1
- CI/CD pipeline setup
- Coverage thresholds or enforcement
- Refactoring the dual `CodeAnalyzer` classes into a shared module (architectural change, separate PRP)

---

## Proposed Solution

### Prerequisites

All required tools are already installed in the project `.venv`: pytest, pytest-cov, coverage, ruff, radon, bandit, mypy, pylint. No new dependencies need to be added.

### Configuration: pyproject.toml

A new `pyproject.toml` at project root for pytest and ruff config:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
```

### Makefile targets

```makefile
VENV := .venv/bin

.PHONY: test lint fmt check

test:
	$(VENV)/pytest tests/ -v

lint:
	$(VENV)/ruff check code_analyzer.py code_reporter.py tests/

fmt:
	$(VENV)/ruff format code_analyzer.py code_reporter.py tests/

check: lint test
```

**Behaviors:**
- All targets use `.venv/bin/` prefix explicitly, so they work without venv activation
- `make check` runs `lint` first, then `test`; if `lint` fails, `test` does not run (standard Make prerequisite behavior)
- `make test` exits non-zero if any test fails
- `make lint` exits non-zero if any violations are found

### Test directory structure

```
tests/
  conftest.py                 # Shared fixtures
  test_analyzer_scoring.py    # code_analyzer._calculate_score, _get_grade
  test_reporter_scoring.py    # code_reporter._calculate_score, _get_grade
  test_reporter_render.py     # render_json, render_markdown output structure
```

### Test cases

**conftest.py — shared fixtures:**

Separate fixtures per dataclass type because field names differ (`CodeMetrics.max_cyclomatic_complexity` vs `FileMetrics.max_complexity`):

- `zero_code_metrics`: `CodeMetrics(file_path="test.py")` with all values at defaults (0)
- `clean_code_metrics`: `CodeMetrics(file_path="test.py")` with no violations (score should be 100)
- `bad_code_metrics`: `CodeMetrics(file_path="test.py")` with high violations across all dimensions
- `zero_file_metrics`: `FileMetrics(file_path="test.py")` with all values at defaults (0)
- `clean_file_metrics`: `FileMetrics(file_path="test.py")` with no violations (score should be 100)
- `bad_file_metrics`: `FileMetrics(file_path="test.py")` with high violations across all dimensions
- `sample_report`: `ProjectReport` with 3 `FileMetrics` of varying scores for rendering tests
- `empty_report`: `ProjectReport` with 0 files

**test_analyzer_scoring.py (code_analyzer.py `_calculate_score` / `_get_grade`):**
- Score is 100 when all metrics are zero (no violations)
- Ruff violations deduct 2 points each, capped at 30
- Complexity > 10 deducts `(cc - 10) * 5` points, capped at 20; complexity <= 10 deducts nothing
- Bandit HIGH deducts 15 each, capped at 30
- Bandit MEDIUM deducts 5 each, capped at 15
- Mypy errors deduct 1 each, capped at 10
- Score never goes below 0 (all caps hit simultaneously)
- Grade returns full Chinese-labeled strings: `"A (优秀)"`, `"B (良好)"`, `"C (一般)"`, `"D (及格)"`, `"F (不及格)"`
- Grade boundary values (all thresholds tested both sides):
  - 90.0 → `"A (优秀)"`, 89.9 → `"B (良好)"`
  - 80.0 → `"B (良好)"`, 79.9 → `"C (一般)"`
  - 70.0 → `"C (一般)"`, 69.9 → `"D (及格)"`
  - 60.0 → `"D (及格)"`, 59.9 → `"F (不及格)"`
  - 0.0 → `"F (不及格)"`

**test_reporter_scoring.py (code_reporter.py `_calculate_score` / `_get_grade`):**

Note: code_reporter uses **different** complexity deduction parameters than code_analyzer. Tests must use reporter-specific constants, not copy from analyzer tests.

- Score is 100 when all metrics are zero (no violations)
- Ruff violations deduct 2 points each, capped at 30
- Complexity > 10 deducts `(cc - 10) * 3` points, capped at 25 (different from analyzer: ×3/cap25 vs ×5/cap20)
- Bandit HIGH deducts 15 each, capped at 30
- Bandit MEDIUM deducts 5 each, capped at 15
- Mypy errors deduct 1 each, capped at 10
- Score never goes below 0 (all caps hit simultaneously)
- Grade returns single-letter strings: `"A"`, `"B"`, `"C"`, `"D"`, `"F"` (no Chinese labels)
- Grade boundary values (all thresholds tested both sides):
  - 90.0 → `"A"`, 89.9 → `"B"`
  - 80.0 → `"B"`, 79.9 → `"C"`
  - 70.0 → `"C"`, 69.9 → `"D"`
  - 60.0 → `"D"`, 59.9 → `"F"`
  - 0.0 → `"F"`

**test_reporter_render.py:**
- `render_json`: output is valid JSON, contains expected top-level keys (`project_path`, `scan_time`, `total_files`, `files`, `avg_score`)
- `render_json`: file entries contain `file_path`, `score`, `max_complexity`
- `render_json` with empty report: valid JSON, `total_files` is 0, `files` is empty list
- `render_markdown`: output contains expected headers (`# 📊 Python 代码质量报告`, `## 总体评分`, `## 评级分布`)
- `render_markdown`: output contains project path and score values from the report
- `render_markdown` with empty report: still produces valid structure, no division-by-zero errors

### Acceptance criteria

- [ ] `make test` runs all tests and exits 0 with all passing
- [ ] `make lint` runs ruff on application code and tests, exits 0
- [ ] `make check` runs lint then test sequentially
- [ ] All scoring boundary conditions are covered (0, cap values, exact grade thresholds)
- [ ] Empty/zero-value inputs do not cause errors in scoring or rendering
- [ ] `CLAUDE.md` updated with new Makefile commands

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dual `CodeAnalyzer` scoring divergence | Tests pass for one but not the other | Test both explicitly; document divergence in test comments |
| Mock drift (if future integration tests mock subprocess) | Mocks pass but real tools fail | v1 avoids mocking entirely; future PRP must define mock update strategy |
| Maintenance overhead of parallel test suites for two analyzers | Double the test updates for scoring changes | Accept for v1; refactoring into shared module is a separate PRP |

---

## Open Questions

None. All questions resolved:
- **pyproject.toml vs Makefile-only**: Resolved — use `pyproject.toml` for pytest and ruff config (Python ecosystem standard), Makefile for developer-facing targets.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
| 2026-03-20 | Round 1 revision: resolved OQ #1, added acceptance criteria, risks section, edge case tests, explicit Makefile behaviors, CLAUDE.md update in scope, venv-independent targets | Frank + Claude Code |
| 2026-03-20 | Round 2 revision: explicit scoring parameters for both analyzers (×5/cap20 vs ×3/cap25), explicit grade return formats (Chinese labels vs single-letter) | Frank + Claude Code |
| 2026-03-20 | Round 3 revision: enumerate all grade boundary test values (90/80/70/60), separate fixtures per dataclass type (CodeMetrics vs FileMetrics), state ruff availability in prerequisites | Frank + Claude Code |
| 2026-03-20 | Approved: Codex 9.5/10 (R4), Gemini 10.0/10 (R3). Both pass COR-1602 strict | Frank + Claude Code |
