# CHG-2132: Analyzer Plugin Protocol and Registry

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Approved
**Date:** 2026-03-23
**Requested by:** Frank
**Priority:** High
**Change Type:** Normal
**Related:** HUA-2129-PRP (Phase 1), HUA-2131-PLN (Milestone 4)

---

## What

Create the `LanguageAnalyzer` protocol, analyzer registry, and file-extension-based language auto-detection. New files only — no changes to existing code.

New files:
- `src/dr_huatuo/analyzers/__init__.py` — registry + `create_analyzer()`
- `src/dr_huatuo/analyzers/base.py` — `LanguageAnalyzer` protocol + `ToolNotFoundError`
- `tests/test_analyzer_registry.py` — tests for registry and auto-detection

## Why

HUA-2129-PRP Phase 1. Establishes the plugin interface that `PythonAnalyzer` (Phase 2) and `TypeScriptAnalyzer` (Phase 5) will implement. Prerequisite for eliminating CodeAnalyzer duplication.

## Impact Analysis

- **Systems affected:** None — new files only, no existing imports change
- **Rollback plan:** Delete `src/dr_huatuo/analyzers/` directory

## Implementation Plan

1. Create `src/dr_huatuo/analyzers/base.py` — `LanguageAnalyzer` protocol with `ClassVar` attributes, `check_tools()`, `analyze_file()`, `analyze_batch()`, `ToolNotFoundError`
2. Create `src/dr_huatuo/analyzers/__init__.py` — `register()`, `get_analyzer_class()`, `create_analyzer()`, `ANALYZERS` dict
3. Create `tests/test_analyzer_registry.py` — test register, lookup by extension, unknown extension returns None, create_analyzer instantiation
4. `make check` passes (503+ tests)

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
