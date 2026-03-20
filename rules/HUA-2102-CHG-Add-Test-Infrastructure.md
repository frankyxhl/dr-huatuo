# CHG-2102: Add Test Infrastructure

- **Date:** 2026-03-20
- **Requested by:** Frank
- **Status:** Completed
- **Priority:** Medium
- **Change Type:** Normal
- **Scheduled:** 2026-03-20
- **Related:** HUA-2100-PRP (Approved)

---

## What

Add a Makefile, pyproject.toml, and tests/ directory to the huatuo project. The Makefile provides standardized developer commands: `make test` (pytest), `make lint` (ruff check), `make fmt` (ruff format), and `make check` (lint + test). The tests/ directory contains unit tests covering:

- Scoring logic for both `code_analyzer.py` (complexity: ×5/cap20, grades: Chinese-labeled) and `code_reporter.py` (complexity: ×3/cap25, grades: single-letter)
- All grade boundary thresholds (90, 80, 70, 60) tested on both sides
- Report rendering output structure (JSON validity and keys, Markdown headers)
- Edge cases: zero-value metrics, empty file lists, empty project reports

CLAUDE.md is updated to document the new Makefile commands.

---

## Why

The project has no tests or standardized development commands. Two separate `CodeAnalyzer` classes exist (`code_analyzer.py` and `code_reporter.py`) with divergent scoring parameters — changes to one can silently break the other. Contributors must manually verify every change by running scripts and inspecting output. There is no lint or format entry point for the project's own code.

---

## Impact Analysis

- **Systems affected:** Project root — new files: Makefile, pyproject.toml, tests/conftest.py, tests/test_analyzer_scoring.py, tests/test_reporter_scoring.py, tests/test_reporter_render.py. One existing file modified: CLAUDE.md (adding Makefile command documentation).
- **Channels affected:** None (internal developer tooling only)
- **Downtime required:** No
- **Rollback plan:** Delete Makefile, pyproject.toml, and tests/ directory. For CLAUDE.md, revert only the added Makefile command section (remove the `make test`, `make lint`, `make fmt`, `make check` documentation lines added in step 8); do not use `git checkout --` as it may clobber unrelated edits.

---

## Implementation Plan

1. Create `pyproject.toml` with pytest and ruff configuration
2. Create `Makefile` with test, lint, fmt, check targets (using `.venv/bin/` prefix for venv-independent execution)
3. Create `tests/conftest.py` with separate fixtures per dataclass type: `zero/clean/bad_code_metrics` (CodeMetrics, field: `max_cyclomatic_complexity`) and `zero/clean/bad_file_metrics` (FileMetrics, field: `max_complexity`), plus `sample_report` and `empty_report` ProjectReport fixtures
4. Create `tests/test_analyzer_scoring.py` — `_calculate_score` (ruff: -2/cap30, complexity >10: ×5/cap20, bandit HIGH: -15/cap30, MEDIUM: -5/cap15, mypy: -1/cap10, floor at 0) and `_get_grade` (returns `"A (优秀)"` etc., all thresholds both sides)
5. Create `tests/test_reporter_scoring.py` — `_calculate_score` (complexity >10: ×3/cap25, otherwise same caps) and `_get_grade` (returns `"A"` etc., all thresholds both sides)
6. Create `tests/test_reporter_render.py` — `render_json`: valid JSON, top-level keys (`project_path`, `scan_time`, `total_files`, `files`, `avg_score`), file entries contain `file_path`/`score`/`max_complexity`; empty report produces valid JSON with `total_files: 0`. `render_markdown`: expected headers present, project path and scores in output; empty report has no division-by-zero errors
7. Run `make check` to verify lint + test pass
8. Update CLAUDE.md with `make test`, `make lint`, `make fmt`, `make check` commands

Implementation follows COR-1500 TDD: write failing tests first, then verify they pass against existing code.

---

## Testing / Verification

- `make test` exits 0 with all tests passing
- `make lint` runs ruff on `code_analyzer.py`, `code_reporter.py`, and `tests/`, exits 0
- `make check` runs lint first, then test; fails if either fails
- Scoring cap values verified for each deduction dimension:
  - Ruff: 15+ violations → capped at 30 (not 30+)
  - Complexity (analyzer): cc=25 → deduction capped at 20
  - Complexity (reporter): cc=25 → deduction capped at 25
  - Bandit HIGH: 2+ → capped at 30
  - Bandit MEDIUM: 3+ → capped at 15
  - Mypy: 10+ → capped at 10
- Score floor at 0: `CodeMetrics` and `FileMetrics` with all caps maxed simultaneously produce score 0, not negative
- All grade boundary values tested on both sides: 90/89.9, 80/79.9, 70/69.9, 60/59.9, 0
- Empty/zero-value inputs: `CodeMetrics` with all zeros, `FileMetrics` with all zeros, `ProjectReport` with empty files list — no errors in scoring or rendering
- JSON render: output parses as valid JSON with expected keys
- Markdown render: output contains expected section headers
- CLAUDE.md contains `make test`, `make lint`, `make fmt`, `make check` documentation
- **Rollback verification:** After deleting Makefile, pyproject.toml, and tests/, and removing the added Makefile command lines from CLAUDE.md, verify `python code_analyzer.py example_code.py` and `python code_reporter.py . -f json` execute without errors

---

## Approval

- [x] Reviewed by: Codex (9.4/10 R3), Gemini (9.9/10 R2)
- [x] Approved on: 2026-03-20

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|

---

## Post-Change Review

_(to be filled after implementation)_

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version per HUA-2100-PRP | Frank + Claude Code |
| 2026-03-20 | R1 revision: self-contained What/Why, fixed Impact Analysis (CLAUDE.md is modified), added Channels affected, expanded Testing/Verification to match all PRP acceptance criteria, added rollback verification | Frank + Claude Code |
| 2026-03-20 | R2 revision: surgical CLAUDE.md rollback (no git checkout --), enumerate all cap-value checks explicitly (no "etc."), zero-value testing covers both CodeMetrics and FileMetrics | Frank + Claude Code |
