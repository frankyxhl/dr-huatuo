# CHG-2134: Rename Python Fields to Generic Names

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Proposed
**Date:** 2026-03-23
**Requested by:** Frank
**Priority:** High
**Change Type:** Normal
**Related:** HUA-2129-PRP (Phase 3), HUA-2133-CHG (Phase 2)

---

## What

Rename Python-specific field names to language-neutral names in `CodeMetrics` and `FileMetrics` dataclasses, plus all in-scope consumers and tests. Add `__getattr__` backward-compat aliases on both dataclasses so out-of-scope research modules continue to work.

Rename map:

| Old (Python-specific) | New (generic) |
|---|---|
| `ruff_violations` | `lint_violations` |
| `pylint_score` | `linter_score` |
| `bandit_high` | `security_high` |
| `bandit_medium` | `security_medium` |
| `mypy_errors` | `type_errors` |

## Why

HUA-2129-PRP Phase 3. Generic names are required for the multi-language plugin protocol — `ruff_violations` is meaningless for TypeScript.

## Impact Analysis

**Modified (in-scope):**
- `code_analyzer.py` — `CodeMetrics` fields + `_calculate_score` + `_run_*` methods + `print_report` (~25 refs)
- `code_reporter.py` — `FileMetrics` fields + `_calculate_score` + `analyze_file` (~31 refs)
- `quality_profile.py` — field reads in rating functions (~26 refs)
- `cli.py` — remaining legacy refs (~2 refs)
- `analyzers/python.py` — dual-emit legacy names become primary; remove old legacy section (~10 refs)
- `conftest.py` — fixture field names (~28 refs)
- `tests/test_analyzer_scoring.py` (~23 refs)
- `tests/test_reporter_scoring.py` (~23 refs)
- `tests/test_quality_profile.py` (~66 refs)
- `tests/test_reporter_refactor.py` (~16 refs)
- `tests/test_cli.py` (~2 refs)
- `tests/test_python_analyzer.py` (~10 refs)

**Not modified (out-of-scope — use `__getattr__` aliases):**
- `dataset_annotator.py` (32 refs), `scoring_optimizer.py` (30 refs), `bugsinpy_analysis.py` (5 refs)
- `tests/test_scoring_optimizer.py` (128 refs), `tests/test_dataset_annotator.py` (75 refs), `tests/test_bugsinpy_analysis.py` (23 refs)

**Rollback plan:** `git revert`

## Implementation Plan

1. Rename fields in `CodeMetrics` dataclass (`code_analyzer.py`) + add `__getattr__` for old names with `DeprecationWarning`
2. Update all refs in `code_analyzer.py` (scoring, grade, print_report)
3. Rename fields in `FileMetrics` dataclass (`code_reporter.py`) + add `__getattr__`
4. Update all refs in `code_reporter.py` (scoring, analyze_file)
5. Update `quality_profile.py` field reads
6. Update `analyzers/python.py` — generic names become primary, keep dual-emit for legacy consumers
7. Update `conftest.py` fixtures
8. Update each test file one at a time, `make test` after each
9. `make check` passes, `ruff format --check` passes
10. Verify research module tests still pass via `__getattr__` aliases

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
