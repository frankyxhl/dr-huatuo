# CHG-2133: Extract PythonAnalyzer from CodeAnalyzer

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Proposed
**Date:** 2026-03-23
**Requested by:** Frank
**Priority:** High
**Change Type:** Normal
**Related:** HUA-2129-PRP (Phase 2), HUA-2131-PLN (Milestone 4), HUA-2132-CHG (Phase 1)

---

## What

Create `PythonAnalyzer` in `src/dr_huatuo/analyzers/python.py` that implements the `LanguageAnalyzer` protocol by **wrapping** the existing `CodeAnalyzer` from `code_analyzer.py` (not duplicating its subprocess logic). It combines:
- `CodeAnalyzer.analyze()` results (ruff, bandit, mypy, pylint via subprocess)
- Layer 2 metrics currently in `cli.py`'s `_gather_layer2()` (radon MI via Python API, complexipy via Python API, AST-based nesting/docstring/comment metrics)
- Metrics dict construction currently in `cli.py`'s `_build_metrics_dict()`

Then update `cli.py` to use `PythonAnalyzer` via the registry instead of direct calls.

**This phase introduces temporary duplication** — `code_analyzer.py`'s `CodeAnalyzer` continues to exist unchanged for backward compatibility. Unification is deferred to a follow-up after Phase 3–4 field renames.

## Why

HUA-2129-PRP Phase 2. Centralizes Python analysis behind the plugin protocol so `cli.py` is language-agnostic. Prerequisite for multi-language support (the registry dispatches by file extension).

## Impact Analysis

- **New files:**
  - `src/dr_huatuo/analyzers/python.py` — `PythonAnalyzer(BaseAnalyzer)`
  - `tests/test_python_analyzer.py` — tests for PythonAnalyzer
- **Modified:**
  - `cli.py` — `cmd_check()` uses `PythonAnalyzer` via registry; `_gather_layer2()`, `_build_metrics_dict()`, and AST helpers (`_max_nesting_depth`, `_docstring_density`, `_comment_density`, `_count_classes`, `_CONTROL_FLOW_NODES`) move into `PythonAnalyzer`; remove unused `from dr_huatuo.code_analyzer import CodeAnalyzer, CodeMetrics`
  - `tests/test_cli.py` — `TestGatherLayer2` (~10 tests) and `TestBuildMetricsDict` migrate to `tests/test_python_analyzer.py` (testing `PythonAnalyzer.analyze_file()` instead)
  - `src/dr_huatuo/analyzers/__init__.py` — import and auto-register `PythonAnalyzer`
- **Unchanged:** `code_analyzer.py`, `code_reporter.py`, `quality_profile.py`
- **Rollback plan:** Revert `cli.py` and `tests/test_cli.py` changes, delete `analyzers/python.py` and `tests/test_python_analyzer.py`, remove registration from `analyzers/__init__.py`

## Implementation Plan

1. **Create `src/dr_huatuo/analyzers/python.py`:**
   - `PythonAnalyzer(BaseAnalyzer)` with ClassVars: `name = "python"`, `extensions = [".py"]`, `critical_tools = ["ruff", "radon", "bandit", "mypy"]`, `optional_tools = ["pylint", "complexipy"]`
   - `__init__(self, project_root=None)`: calls `_ensure_venv_on_path()` + `check_tools()`
   - `check_tools()`: uses `shutil.which()` for each tool; raises `ToolNotFoundError` for missing critical tools; warns for missing optional tools
   - `analyze_file(path)`: wraps `CodeAnalyzer().analyze(path)` for Layer 1, runs radon/complexipy/AST for Layer 2, returns the **full protocol dict** including:
     - Legacy names for backward compat: `ruff_violations`, `bandit_high`, `bandit_medium`, `mypy_errors`, `pylint_score` (dual-emit so `quality_profile.py` works unchanged)
     - Generic names: `lint_violations`, `security_high`, `security_medium`, `type_errors`, `linter_score`
     - Protocol-required keys: `language="python"`, `data_warnings=[]`, `error_type=None`, `error_detail=None`, `tool_errors=None`, Halstead fields from radon (`n1`, `n2`, `N1`, `N2`, `halstead_volume`, `halstead_difficulty`, `halstead_effort` — None if radon unavailable)
   - Move AST helpers from `cli.py`: `_max_nesting_depth()`, `_docstring_density()`, `_comment_density()`, `_count_classes()`, `_CONTROL_FLOW_NODES`

2. **Register in `src/dr_huatuo/analyzers/__init__.py`:**
   - Add `from dr_huatuo.analyzers.python import PythonAnalyzer` and `register(PythonAnalyzer)` at module level (import-time side effect)

3. **Update `cli.py`:**
   - `cmd_check()`: replace `CodeAnalyzer().analyze()` + `_gather_layer2()` + `_build_metrics_dict()` with `create_analyzer(fpath).analyze_file(fpath)`
   - Handle `create_analyzer()` returning `None` for non-Python files: skip with warning `"Unsupported file type: {path.suffix}"`
   - Remove: `_gather_layer2()`, `_build_metrics_dict()`, AST helpers, `_CONTROL_FLOW_NODES`, `import ast`
   - Remove: `from dr_huatuo.code_analyzer import CodeAnalyzer, CodeMetrics`

4. **Migrate tests:**
   - Move `TestGatherLayer2` and `TestBuildMetricsDict` from `tests/test_cli.py` to `tests/test_python_analyzer.py`, adapting to test `PythonAnalyzer.analyze_file()` output
   - Add protocol conformance tests (ClassVars, analyze_batch delegation)

5. **Verify:** `make check` passes (514+ tests, lint clean)

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
| 2026-03-23 | R1 revision: address Codex (4) and Gemini (3) blocking issues — clarify wrapping vs duplication; add dual-emit field names; specify registry wiring; list test migrations; add full protocol dict keys; add ClassVar requirement; add unused import cleanup; describe non-Python file handling | Claude Code |
