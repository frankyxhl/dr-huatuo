# CHG-2105: Fix Type Errors

- **Date:** 2026-03-21
- **Requested by:** Frank
- **Status:** Completed
- **Priority:** Medium
- **Change Type:** Normal
- **Scheduled:** 2026-03-21
- **Related:** HUA-2103-CHG

---

## What

Fix 16 mypy type errors across `code_analyzer.py` (10 errors) and `code_reporter.py` (6 errors).

**code_analyzer.py (10 errors):**
- 3 errors: `CodeMetrics` list fields (`ruff_errors`, `mypy_warnings`, `bandit_issues`) default to `None` but typed as `list`
- 1 error: `analyze()` reassigns `path` from `str` to `Path`
- 1 error: `path.exists()` called on `str`
- 5 errors: `_run_*` methods receive `str` but expect `Path`

**code_reporter.py (6 errors):**
- 3 errors: implicit `Optional` on `exclude`, `console`, `output_file` parameters
- 2 errors: `analyze_project()` reassigns `path` from `str` to `Path` + `str.rglob()`
- 1 error: `generate_report(output_file)` implicit Optional

**Design decision:** Use `field(default_factory=list)` for `CodeMetrics` list fields and **remove `__post_init__`** entirely. This is cleaner than `Optional[list]` because:
- All downstream code treats these fields as definite lists (e.g., `metrics.bandit_issues[:3]` at line 318)
- `Optional[list]` would create new mypy errors at every indexing/slicing site
- `field(default_factory=list)` makes the invariant visible to mypy without runtime guards

Note: `code_reporter.py` dataclasses already use `field(default_factory=list)` — no changes needed there.

Dropping `__post_init__` means callers can no longer pass `None` for list fields and get automatic normalization. This is an intentional cleanup — no in-repo callers pass explicit `None` for these fields. Fields will be typed as `list[Any]` (not bare `list`).

For path parameters: use `resolved = Path(path)` as a new variable (not reassignment, not `.resolve()` — preserves original path strings in output).

---

## Why

16 mypy errors reduce the project's quality score. Fixing these improves type safety and enables mypy to catch real bugs.

---

## Impact Analysis

- **Systems affected:**
  - `code_analyzer.py` — `CodeMetrics` dataclass: 3 field type changes + remove `__post_init__`; `analyze()`: parameter broadened to `str | Path`
  - `code_reporter.py` — 3 function signatures get explicit `Optional`; `analyze_project()` path handling
  - `tests/conftest.py` — verify fixtures still construct correctly without `__post_init__`
- **Channels affected:** None — runtime behavior unchanged, callers already pass `str` or `None`
- **Downtime required:** No
- **Rollback plan:** `git revert` the commit.

---

## Implementation Plan

1. Fix `code_analyzer.py` `CodeMetrics` dataclass (lines 26, 31, 36):
   - `ruff_errors: list = None` → `ruff_errors: list[Any] = field(default_factory=list)`
   - `mypy_warnings: list = None` → `mypy_warnings: list[Any] = field(default_factory=list)`
   - `bandit_issues: list = None` → `bandit_issues: list[Any] = field(default_factory=list)`
   - Delete `__post_init__` (lines 42-48) — no longer needed
   - Add `from dataclasses import field` to imports if not present
2. Fix `code_analyzer.py` `analyze()` (line 97):
   - Change `path: str` to `path: str | Path`
   - Replace `path = Path(path)` with `resolved = Path(path)`
   - Use `resolved` in all subsequent calls (`resolved.exists()`, `_run_ruff(resolved)`, etc.)
3. Fix `code_reporter.py` signatures:
   - Line 135: `analyze_project(self, path: str, exclude: list = None)` → `path: str | Path, exclude: Optional[list[str]] = None`; add `resolved = Path(path)`, use for `.rglob()`. Runtime unchanged: `None` triggers default exclude.
   - Line 477: `ReportRenderer.__init__(self, console: Console = None)` → `console: Optional[Console] = None`. Runtime unchanged: `None` creates new `Console()`.
   - Lines 2044-2045: `generate_report(path: str, ..., exclude: list = None, output_file: str = None)` → `path: str | Path, ..., exclude: Optional[list[str]] = None, output_file: Optional[str] = None`. Runtime unchanged.
4. Run `.venv/bin/mypy code_analyzer.py code_reporter.py --no-error-summary` — verify 0 errors
5. Run `make check` — verify ruff + pytest pass (note: make check does not run mypy; step 4 is the mypy gate)
6. Add tests using `tmp_path` fixture:
   - `CodeMetrics(file_path="x").ruff_errors` is `[]` (not `None` — default_factory works)
   - `CodeMetrics(file_path="x").bandit_issues` is `[]`
   - Create a dummy `.py` file in `tmp_path`, verify `CodeAnalyzer().analyze(tmp_path / "dummy.py")` accepts `Path` input without error (monkeypatch subprocess to avoid tool dependency)

---

## Testing / Verification

- `.venv/bin/mypy code_analyzer.py` reports 0 errors (down from 10)
- `.venv/bin/mypy code_reporter.py` reports 0 errors (down from 6)
- `make check` passes (0 lint violations, all tests pass)
- `CodeMetrics(file_path="x").ruff_errors == []` (default_factory, not None)
- `CodeMetrics(file_path="x").bandit_issues == []` (default_factory, not None)
- Path input accepted at all three entry points:
  - `code_analyzer.py:86` — `CodeAnalyzer().analyze(Path(...))`
  - `code_reporter.py:135` — `CodeAnalyzer().analyze_project(Path(...))`
  - `code_reporter.py:2044` — `generate_report(Path(...))`
- Note: `make check` does not run mypy — `.venv/bin/mypy` is the type gate
- Note: `resolved = Path(path)` is NOT `.resolve()` — path strings in output remain unchanged
- **Rollback verification:** After `git revert`, mypy errors return to 16

---

## Approval

- [x] Reviewed by: Codex (9.1/10 R7), Gemini (10/10 R6)
- [x] Approved on: 2026-03-21

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
| 2026-03-20 | R1-R4 revisions: baseline corrections, signature details | Frank + Claude Code |
| 2026-03-21 | R5 revision: switch from Optional[list] to field(default_factory=list) + remove __post_init__ (avoids new mypy errors at indexing sites), use tmp_path for Path regression tests, add None-normalization test, clarify resolved vs .resolve() | Frank + Claude Code |
