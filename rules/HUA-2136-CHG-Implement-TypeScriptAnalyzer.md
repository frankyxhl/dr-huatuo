# CHG-2136: Implement TypeScriptAnalyzer

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Proposed
**Date:** 2026-03-23
**Requested by:** Frank
**Priority:** High
**Change Type:** Normal
**Related:** HUA-2129-PRP (Phase 5), HUA-2131-PLN (Milestone 5)
**Depends on:** HUA-2132 (Phase 1), HUA-2133 (Phase 2), HUA-2134 (Phase 3+4) — all merged to main

---

## What

Create `TypeScriptAnalyzer` in `src/dr_huatuo/analyzers/typescript.py` implementing the `LanguageAnalyzer` protocol for `.ts` and `.tsx` files. Uses Node.js-based tools via subprocess with batch processing to avoid per-file startup overhead.

Update `cli.py` to support multi-language file discovery and per-language batch analysis.

## Why

HUA-2129-PRP Phase 5. Extends dr-huatuo from Python-only to multi-language. Users can run `ht check src/` on a mixed Python + TypeScript project and get quality profiles for both.

## Impact Analysis

**New files:**
- `src/dr_huatuo/analyzers/typescript.py` — `TypeScriptAnalyzer(BaseAnalyzer)`
- `tests/test_typescript_analyzer.py`

**Modified:**
- `src/dr_huatuo/analyzers/__init__.py` — register `TypeScriptAnalyzer` unconditionally (error deferred to analysis time, not import time)
- `src/dr_huatuo/cli.py` — registry-driven file discovery + per-language batch dispatch + `--language` filter flag
- `README.md` — roadmap checkbox + TypeScript in Quick Start

**Unchanged:** `code_analyzer.py`, `code_reporter.py`, `quality_profile.py`

**Rollback plan:** Delete `typescript.py` and tests, remove registration, revert CLI changes

## Implementation Plan

### 1. Create `src/dr_huatuo/analyzers/typescript.py`

**ClassVars:**
```python
name = "typescript"
extensions = [".ts", ".tsx"]
critical_tools = ["node", "eslint"]
optional_tools = ["tsc", "escomplex"]
```

Note: `eslint-plugin-security` and `eslint-plugin-sonarjs` are eslint plugins, not standalone executables — cannot be detected via `shutil.which()`. Detection deferred to eslint invocation: if the plugin is not installed, eslint reports a config error, which the analyzer catches and sets `security_high = None`, `cognitive_complexity = None`.

**`__init__(self, project_root=None)`:**
- `project_root` used for `tsconfig.json` and `.eslintrc` / `eslint.config.js` resolution
- If no config files found at project_root, use eslint recommended config and tsc strict mode
- Calls `check_tools()` — raises `ToolNotFoundError` for missing `node` or `eslint`; warns for missing optional tools

**`check_tools()`:**
- `node`: `shutil.which("node")`
- `eslint`: `shutil.which("eslint")` (or `npx eslint` fallback)
- `tsc`: `shutil.which("tsc")` (optional — only for type checking)
- `escomplex`: try `node -e "require('typhonjs-escomplex')"` to verify npm package availability

**`analyze_file(path)` — full protocol dict:**

| Key | Source | Null behavior |
|---|---|---|
| `lint_violations` | eslint `--format json` | 0 if eslint succeeds |
| `linter_score` | None | Always None (no pylint equivalent) |
| `security_high` | eslint-plugin-security findings (HIGH) | None if plugin not installed |
| `security_medium` | eslint-plugin-security findings (MEDIUM) | None if plugin not installed |
| `type_errors` | `tsc --noEmit --pretty false` error count | None if tsc not installed |
| `cyclomatic_complexity` | escomplex | None if escomplex not installed |
| `avg_complexity` | escomplex | None if escomplex not installed |
| `cognitive_complexity` | eslint-plugin-sonarjs | None if plugin not installed |
| `maintainability_index` | escomplex | None if escomplex not installed |
| `max_nesting_depth` | eslint `max-depth` rule or text analysis | 0 |
| `loc` | line count | Always computed |
| `function_count` | regex count of `function` / `=>` patterns | Always computed |
| `class_count` | regex count of `class` keyword | Always computed |
| `comment_density` | `//` and `/* */` line count / loc | Always computed |
| `docstring_density` | JSDoc `/** */` count / function count | Always computed |
| `n1`, `n2`, `N1`, `N2`, `halstead_*` | None | Always None (escomplex Halstead not reliable for TS) |
| `language` | `"typescript"` | Always set |
| `data_warnings` | List of strings for degraded metrics | `[]` if all tools available; e.g. `["no_escomplex: MI unavailable"]` |
| `error_type` | `None` on success; `"tool_error"` or `"parse_error"` on failure | Set when a file cannot be analyzed |
| `error_detail` | `None` on success; error message string on failure | Set when a file cannot be analyzed |
| `tool_errors` | `None` on success; `{"eslint": "msg", "tsc": "msg"}` dict on partial failure | Set when individual tools fail but others succeed |

**Subprocess error handling:**
- **Exit code convention:** eslint exits 1 when violations found (not a crash) — check `stdout` for valid JSON before treating as error. tsc exits 1 on type errors (not a crash). escomplex exits 0 or crashes.
- **Timeouts:** 60s per tool invocation (same as Python tools). On timeout, set tool's metrics to None, add to `tool_errors` and `data_warnings`.
- **Malformed JSON:** `json.JSONDecodeError` caught per tool, metrics set to None, error logged in `tool_errors`.
- **Per-file attribution from batch runs:** eslint JSON output includes file paths; tsc output includes file:line; results split per file after batch execution.

**`analyze_batch(paths)` — batch override:**
- Run eslint once on all files: `eslint --format json file1.ts file2.ts ...`
- Run tsc once (if installed): `tsc --noEmit --pretty false` on project root
- Run escomplex once per file (no batch mode)
- Split results per file from JSON output, return list in same order as input paths
- If a file has no results from a batch tool (e.g., not included in tsconfig), set those metrics to None

### 2. Register in `src/dr_huatuo/analyzers/__init__.py`

**Unconditional registration** — no try/except guard:
```python
from dr_huatuo.analyzers.typescript import TypeScriptAnalyzer
register(TypeScriptAnalyzer)
```
Error surfaces at analysis time when `TypeScriptAnalyzer.__init__` calls `check_tools()`, not at import time. This matches the PRP's design: "ht check gracefully handles missing tools."

### 3. Update `src/dr_huatuo/cli.py`

**Registry-driven file discovery:**
- `_discover_files()` yields files matching any registered extension (`.py`, `.ts`, `.tsx`), not just `*.py`
- New helper: `_supported_extensions()` returns set of extensions from `ANALYZERS` registry

**Per-language batch dispatch in `cmd_check()`:**
- Group discovered files by extension
- For each extension group: create analyzer once, call `analyzer.analyze_batch(files)`
- Results fed to `profile_file()` and rendered as before

**`--language` filter flag:**
- `ht check src/ --language python` — only analyze `.py` files
- `ht check src/ --language typescript` — only `.ts`/`.tsx`
- Default: all registered languages

### 4. Tests in `tests/test_typescript_analyzer.py`

**Unit tests (mocked subprocess):**
- eslint JSON output parsing (violations, security findings)
- tsc output parsing (type error count)
- escomplex output parsing (complexity metrics)
- Malformed JSON handling → metrics set to None, tool_errors populated
- Subprocess timeout → graceful degradation
- Missing eslint-plugin-security → security fields None
- Missing tsc → type_errors None

**Protocol conformance:**
- ClassVars correct
- analyze_batch returns correct length and order
- All protocol keys present in output dict

**CLI integration:**
- Mixed .py + .ts discovery returns both
- `--language python` filters to .py only
- `--language typescript` filters to .ts/.tsx only
- Python files still analyze when TS tooling unavailable (partial failure)

**Skip guard:** `pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")` for integration tests that need real Node.js

### 5. CI

- Add `actions/setup-node@v4` step to test matrix
- Install eslint + typescript globally: `npm install -g eslint typescript`
- TS integration tests run in CI; unit tests (mocked) always run

### 6. Update README

- Check roadmap "Multi-Language" checkbox
- Add TypeScript example to Quick Start

### 7. Verify

- `make check` passes (530+ tests)
- `ruff format --check` passes
- `ht check` works on a mixed .py + .ts directory

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
| 2026-03-23 | R1 revision: address Codex (6) + Gemini (5) blocking issues — unconditional registration; batch dispatch in CLI; full protocol key mapping with null behavior; eslint plugin detection strategy; subprocess error/timeout/JSON handling; --language flag; comment/docstring density; error fields; expanded test plan; explicit Phase 1-4 dependency | Claude Code |
