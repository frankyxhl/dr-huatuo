# PRP-2109: Dataset Annotation Pipeline

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Requested by:** Frank
**Priority:** High

---

## What Is It?

A new module `dataset_annotator.py` that uses huatuo's existing analysis tools as a **scalable batch labeler** for external Python code datasets. It ingests a directory of Python files or a JSONL manifest, runs analysis per file, and outputs per-file quality records in JSON Lines (JSONL) format — structured for downstream ML training or dataset curation.

---

## Problem

The two research reports in `incomings/` independently identify Bandit, Pylint, ruff, radon, and mypy as the recommended "scalable static analysis annotators" for constructing good/bad Python code datasets (chatgpt-report §"静态分析工具作为可规模化标注器"; gemini-report §"静态分析工具的应用"). Huatuo already orchestrates all five tools.

However, the existing `code_reporter.py` is built for **project health dashboards** (terminal/HTML/Markdown/JSON summaries for one codebase). The research use case differs in three key ways:

| Dimension | code_reporter.py | Research use case |
|-----------|-----------------|-------------------|
| Scale | One project (~tens of files) | Thousands of files from external datasets |
| Output | Rich rendering (HTML, terminal) | Stable JSONL schema for ML pipelines |
| Metadata | File paths only | Source dataset + license must be preserved per record |

Adding this to `code_reporter.py` would bloat it and mix concerns.

## Proposed Solution

A new `dataset_annotator.py` module with a `DatasetAnnotator` class.

### Architecture

`DatasetAnnotator` uses a **two-layer analysis model**. Both layers run tools directly — `DatasetAnnotator` does **not** delegate to `CodeAnalyzer`. This decoupling is necessary because research-grade annotation requires per-tool isolation flags, per-tool timeout, and per-tool error tracking, none of which `CodeAnalyzer` supports.

1. **Layer 1 — 5-tool pipeline (run directly by `DatasetAnnotator`)**: each tool is invoked via `subprocess.run()` with isolation flags and per-tool timeout. The tool-running logic mirrors `CodeAnalyzer`'s subprocess calls but adds isolation and error semantics. The scoring formula (`_calculate_score()` and `_get_grade()`) is reimplemented as standalone functions in `dataset_annotator.py` (see Scoring Formula section below).

   | Tool | Output fields | Isolation | Notes |
   |---|---|---|---|
   | ruff | `ruff_violations` | `--isolated` | |
   | radon cc | `cyclomatic_complexity`, `function_count` | _(no config)_ | |
   | bandit | `bandit_high`, `bandit_medium` | `-c /dev/null` | |
   | mypy | `mypy_errors` | `--config-file /dev/null` | Environment-sensitive |
   | pylint | `pylint_score` | `--rcfile /dev/null` | `null` when `--no-pylint` |
   | _(scoring)_ | `score`, `grade` | — | Standalone `_calculate_score()` + `_get_grade()` (see below) |

   Each tool subprocess gets `timeout=tool_timeout` (default 30s). If a tool fails or times out, its fields are `null` and the failure is recorded in `tool_errors` (see below). Other tools continue.

2. **Layer 2 — additional analysis (radon Python API, complexipy, AST)**: metrics computed in-process, not via subprocess:
   - **`h_visit(src)`** (radon) — raw Halstead counts (`n1/n2/N1/N2`), `halstead_volume`, `halstead_difficulty`, `halstead_effort`
   - **`cc_visit(src)`** (radon) — `avg_complexity` (average cyclomatic complexity per function)
   - **`mi_visit(src)`** (radon) — `maintainability_index`
   - **`complexipy`** — `cognitive_complexity` (always required; install with `pip install complexipy`)
   - **AST walk** — `class_count`, `loc`, `max_nesting_depth`, `fanout_modules`, `fanout_symbols`, `comment_density`, `docstring_density`
   - **`lcom` package** (optional, `--full` only) — `lcom4_approx`, `lcom5_hs`
   - **AST call analysis** (optional, `--full` only) — `cbo_approx_static`, `resolved_external_calls`, `unresolved_dynamic_calls`, `cbo_resolution_rate`

**Scoring formula:** `_calculate_score()` and `_get_grade()` are **reimplemented as standalone functions** inside `dataset_annotator.py`. They are NOT imported from `code_analyzer.py` because those are instance methods on `CodeAnalyzer` taking a `CodeMetrics` dataclass with different field names (e.g., `max_cyclomatic_complexity` vs output `cyclomatic_complexity`). The formula is trivial (~20 lines) and fully documented in CLAUDE.md — reimplementing avoids coupling to `CodeAnalyzer`'s internal dataclass. The test suite must verify that both implementations produce identical results for the same inputs.

**Relationship to existing modules:** `code_analyzer.py` and `code_reporter.py` are unchanged. `DatasetAnnotator` reimplements both the tool-invocation layer (with isolation + per-tool error semantics) and the scoring formula (as standalone functions). This is deliberate duplication in exchange for research-grade control and zero coupling to the existing dashboard-oriented modules.

### Tool config isolation

When analysing external datasets, tools must not be influenced by config files in the analysed project's directory tree (`pyproject.toml`, `mypy.ini`, `.pylintrc`, `ruff.toml`, `.bandit`, etc.). This is critical for annotation consistency: the same file should produce the same metrics regardless of where it lives on disk.

Each tool is invoked with explicit isolation flags:

| Tool | Isolation flag | Effect |
|---|---|---|
| ruff | `--isolated` | Ignores all config files (ruff.toml, pyproject.toml) |
| mypy | `--config-file /dev/null` | Ignores mypy.ini, pyproject.toml [mypy] |
| pylint | `--rcfile /dev/null` | Ignores .pylintrc, pyproject.toml [pylint] |
| bandit | `-c /dev/null` | Ignores .bandit, pyproject.toml [bandit] |
| radon | _(no config file)_ | CLI-only; no isolation needed |

**Note on mypy/pylint false positives:** Even with config isolation, `mypy_errors` and `pylint_score` are affected by missing dependencies, stubs, and package context in single-file analysis. For example, `import numpy` in an isolated file will generate `mypy` import-not-found errors and `pylint` import-error messages that reflect the analysis environment, not code quality. This is an inherent limitation of single-file static analysis on external datasets. `data_warnings` should flag records with unusually high `mypy_errors` relative to `loc` (heuristic: `mypy_errors / loc > 0.3` → `"suspect:mypy_env"`), but downstream ML pipelines should treat `mypy_errors` and `pylint_score` as **environment-sensitive signals**, not ground-truth labels.

**Note on `inspect4py`:** HUA-2112 recommends `inspect4py` for structural fields. For v1, custom AST is used instead — lighter dependency, no CFG overhead needed for Tier 1 fields. `inspect4py` is the recommended path for a future Tier 2 structural expansion.

**Note on `essential_complexity`:** HUA-2111 Q4 listed `essential_complexity` as Tier 1. It is omitted from this PRP because radon's Python API (`cc_visit()`) does not expose essential complexity as a stored field — the `Block` namedtuple provides `complexity` (cyclomatic) and `closures`, but not the McCabe essential complexity reduction. `cognitive_complexity` and `cyclomatic_complexity` together provide equivalent discriminative power per HUA-2111 Q4 findings.

### Class structure

```python
DatasetAnnotator
  __init__(venv_python=None, run_pylint=True, full=False, workers=1, tool_timeout=30, isolated=True)
  annotate_directory(path, exclude=[]) -> Iterator[dict]
  annotate_manifest(manifest_path) -> Iterator[dict]   # reads JSONL with per-file metadata
  annotate_file(path, source="", license="") -> dict
```

- `run_pylint=False`: `pylint_score` is emitted as `null` (not `0.0` — a zero score is misleading training data).
- `full=True`: enables Tier 2 fields; requires `lcom` package.
- `workers=N`: parallel file processing via `concurrent.futures.ProcessPoolExecutor`.

### JSONL output schema

The schema is split into two tiers. Tier 1 fields are always present. Tier 2 fields are emitted only with `--full`.

#### Tier 1 — always present

```json
{
  "schema_version": "1.0",
  "annotator_version": "0.1.0",
  "tool_versions": {
    "ruff": "0.5.0",
    "radon": "6.0.1",
    "bandit": "1.7.9",
    "mypy": "1.11.0",
    "pylint": "3.2.6",
    "complexipy": "0.4.0"
  },
  "analysis_config": {
    "run_pylint": true,
    "full": false,
    "tool_timeout": 30
  },
  "runtime_env": {
    "python_version": "3.13.1",
    "platform": "macOS-15.4-arm64",
    "isolated": true
  },

  "path": "path/to/file.py",
  "content_sha256": "a1b2c3d4...",
  "source": "BugsInPy",
  "license": "MIT",

  "score": 72.0,
  "grade": "C (Fair)",

  "ruff_violations": 3,
  "bandit_high": 0,
  "bandit_medium": 1,
  "mypy_errors": 2,
  "pylint_score": 7.4,

  "loc": 187,
  "function_count": 6,
  "class_count": 2,

  "cyclomatic_complexity": 8,
  "avg_complexity": 4.2,
  "cognitive_complexity": 11,
  "max_nesting_depth": 4,

  "n1": 32,
  "n2": 18,
  "N1": 84,
  "N2": 61,
  "halstead_volume": 842.0,
  "halstead_difficulty": 31.2,
  "halstead_effort": 26270.0,

  "maintainability_index": 52.3,

  "fanout_modules": 4,
  "fanout_symbols": 12,
  "comment_density": 0.08,
  "docstring_density": 0.33,

  "data_warnings": [],
  "tool_errors": null,
  "error_type": null,
  "error_detail": null
}
```

#### Tier 2 — emitted only with `--full`

```json
{
  "lcom4_approx": 2,
  "lcom5_hs": 0.67,
  "lcom_impl_version": "lcom-0.1.0",
  "cbo_approx_static": 4,
  "resolved_external_calls": 8,
  "unresolved_dynamic_calls": 3,
  "cbo_resolution_rate": 0.73
}
```

#### Reproducibility metadata

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `str` | JSONL schema version (e.g. `"1.0"`); bumped on breaking field changes |
| `annotator_version` | `str` | `dataset_annotator.py` version; follows semver |
| `tool_versions` | `dict[str, str]` | Exact version of each tool at analysis time; captured at `__init__()` via `--version` calls |
| `analysis_config` | `dict` | `run_pylint` (bool), `full` (bool), `tool_timeout` (int, seconds); records the exact configuration used |
| `content_sha256` | `str\|null` | SHA-256 of normalised source (`\r\n→\n`, strip trailing whitespace per line). Computed whenever file content can be read — even for syntax errors or analysis failures. `null` **only** when the file itself could not be read (I/O error). Required by HUA-2113-PRP (dedup) |

Additionally, a `runtime_env` block is emitted in every record (same values across all records in a batch; repeated per-record for JSONL self-containedness):

| Field | Type | Notes |
|---|---|---|
| `runtime_env.python_version` | `str` | `sys.version` (e.g. `"3.13.1"`) |
| `runtime_env.platform` | `str` | `platform.platform()` (e.g. `"macOS-15.4-arm64"`) |
| `runtime_env.isolated` | `bool` | Whether tool isolation flags were applied |

These fields make every JSONL record independently verifiable: given the same `content_sha256`, `tool_versions`, `analysis_config`, and `runtime_env`, the metrics should be reproducible. Note: even with identical configuration, `mypy_errors` and `pylint_score` may vary across environments with different installed packages — this is an inherent limitation of single-file static analysis on external datasets (see Tool Config Isolation).

#### Score and grade methodology note

`score` and `grade` are **derived convenience labels**, not ground-truth quality measurements. The scoring formula was originally designed for project-level health dashboards (`code_analyzer.py`), not for per-file ML training labels. The formula applies fixed deduction weights (ruff: -2/violation max -30; complexity: (cc-10)×5 max -20; bandit HIGH: -15 max -30; bandit MEDIUM: -5 max -15; mypy: -1 max -10) that reflect engineering judgment, not empirically validated quality signals.

**For research use:** downstream ML pipelines should treat raw metric fields (`ruff_violations`, `cyclomatic_complexity`, `n1/n2/N1/N2`, etc.) as primary features and `score/grade` as one possible aggregation. The scoring formula and weights are documented in `code_analyzer.py:_calculate_score()` and in CLAUDE.md.

#### Field notes

| Field | Source | Notes |
|---|---|---|
| `cyclomatic_complexity` | DatasetAnnotator / radon cc | Max per file |
| `avg_complexity` | radon `cc_visit()` (Layer 2) | Average per function; not in `CodeMetrics` |
| `cognitive_complexity` | complexipy Python API | Always required; `pip install complexipy` |
| `n1/n2/N1/N2` | radon `h_visit()` | Raw Halstead counts — reproducible, primary inputs |
| `halstead_volume/difficulty/effort` | radon `h_visit()` | Derived from raw counts |
| `halstead_bugs` | — | **Not emitted** — demoted Tier 3 (see HUA-2111 Q1) |
| `maintainability_index` | radon `mi_visit()` | 0–100 scale |
| `fanout_modules` | AST import analysis | Distinct module names in import statements |
| `fanout_symbols` | AST import analysis | Distinct symbols in `from X import y` |
| `pylint_score` | DatasetAnnotator / pylint | `null` when `--no-pylint` (not `0.0`) |
| `lcom4_approx` | lcom package | `--full` only; single-file, no MRO/dynamic resolution |
| `cbo_resolution_rate` | AST call analysis | `--full` only; resolved / (resolved + unresolved) |
| `data_warnings` | DatasetAnnotator | List of strings; populated when tool errors or suspicious zeros detected; empty list = clean |

#### AST metric definitions

Custom metrics computed by Layer 2 AST walk. Formal definitions to ensure implementation consistency:

| Field | Definition | Edge cases |
|---|---|---|
| `loc` | Total lines in file including blanks, comments, and docstrings. Equivalent to `len(source.splitlines())`. | Empty file → 0. File with only `\n` → 1. |
| `class_count` | Count of top-level and nested `class` statements in the AST (`ast.ClassDef` nodes). | No classes → 0. Nested classes counted individually. |
| `max_nesting_depth` | Maximum depth of nested control-flow blocks: `if`, `for`, `while`, `try`, `with`, `async for`, `async with`. Function/class bodies are depth 0; each nested control-flow keyword adds 1. | No control flow → 0. `if` inside `for` inside function → depth 2. |
| `fanout_modules` | Count of **distinct module names** in `import X` and `from X import ...` statements. `from os.path import join` counts `os.path` as one module. | No imports → 0. `import os; import os` → 1. |
| `fanout_symbols` | Count of **distinct imported symbols** across all `from X import y, z` statements. `import X` (no specific symbol) counts as 0 symbols. | `from os import path, getcwd` → 2 symbols. `import os` → 0 symbols. |
| `comment_density` | `comment_lines / loc` where `comment_lines` = lines whose first non-whitespace character is `#` (excluding shebangs `#!` on line 1 and encoding cookies `# -*- coding`). Docstrings are NOT comments. | `loc == 0` → 0.0. File with only comments → 1.0. |
| `docstring_density` | `functions_with_docstring / function_count` where a function "has a docstring" if its body's first statement is `ast.Expr(ast.Constant(str))`. `function_count` includes methods. | `function_count == 0` → 0.0. All functions have docstrings → 1.0. |

#### Failure contract

`DatasetAnnotator` enforces a two-phase failure contract:

1. **Startup validation** — `__init__()` verifies tools are available and captures their versions (stored in `tool_versions`). Validation is **conditional on configuration**: `pylint` is only checked when `run_pylint=True`; `lcom` is only checked when `full=True`; `complexipy` is always checked. Always-required tools: `ruff`, `radon`, `bandit`, `mypy`, `complexipy`. Missing required tools raise immediately.

2. **Per-file error handling** — `annotate_file()` first attempts `ast.parse(src)` to detect syntax errors. If parsing fails, all metric fields are `null`, `error_type="syntax_error"`, and per-tool analysis is skipped. Otherwise, each Layer 1 tool is invoked individually via `subprocess.run()` with isolation flags and timeout.

**Per-tool timeout:** Each tool subprocess is invoked with `timeout=tool_timeout` (default 30s, configurable via `--tool-timeout N`). If a tool exceeds the timeout, its fields are `null` and the failure is recorded in `tool_errors` (e.g., `{"mypy": "timeout"}`). Other tools continue independently.

**Error taxonomy — two levels:**

**File-level error** (entire file cannot be processed):

| Field | Type | Notes |
|---|---|---|
| `error_type` | `str\|null` | `null` = file processed. One of: `syntax_error`, `io_error`, `analysis_exception` |
| `error_detail` | `str\|null` | Human-readable message; `null` when no error |

When `error_type` is set, **all** metric fields are `null` and `tool_errors` is `null` (file was never analysed).

**Per-tool error** (specific tools failed, others succeeded):

| Field | Type | Notes |
|---|---|---|
| `tool_errors` | `dict[str, str]\|null` | `null` when all tools succeeded. Otherwise a dict of `{tool_name: error_reason}` for each tool that failed |

Error reasons: `"timeout"` (exceeded `tool_timeout`), `"crash"` (non-zero exit + no output), `"empty_output"` (tool ran but produced no parseable result).

When a tool appears in `tool_errors`, its corresponding output fields are `null`; other tools' fields are preserved. This enables partial records — e.g., ruff and bandit succeeded but mypy timed out → `ruff_violations=3`, `mypy_errors=null`, `tool_errors={"mypy": "timeout"}`.

Note: `tool_missing` never appears — caught at startup. `suspected_silent_failure` is surfaced via `data_warnings`, not `tool_errors` (it's a heuristic, not a detected error).

Tool installation failures are caught at startup; syntax errors are caught before tool invocation; per-tool failures (timeout, crash, empty output) are recorded in `tool_errors` with affected fields set to `null`.

**Handling silent tool failures:** Even with direct subprocess control, some tools may produce zero/empty output without a non-zero exit code (e.g., ruff returns `[]` for an unparseable file). `data_warnings` provides **best-effort heuristic detection** of such cases — it is not a complete guarantee.

Mitigations that populate `data_warnings`:

1. **Heuristic zero-checks** (applied only when `ast.parse()` succeeds and `loc > 20`): these detect patterns unlikely in well-formed files but consistent with silent tool failures:
   - `"suspect:radon"` — `cyclomatic_complexity == 0` and `function_count == 0` on a non-trivial file
   - `"suspect:pylint"` — `pylint_score == 0.0` when `run_pylint=True` (0.0 is a sentinel that pylint never legitimately returns for parseable Python)
   - `"suspect:mypy"` — `mypy_errors == 0` and `pylint_score < 3.0` (low pylint score with no type errors is inconsistent)
   - `"suspect:mypy_env"` — `mypy_errors / loc > 0.3` (excessive type errors relative to file size likely indicates missing dependencies/stubs, not genuinely bad code)

   These heuristics are non-contractual diagnostics. They improve dataset hygiene without guaranteeing complete detection of all silent-zero records. Downstream ML pipelines should treat `data_warnings` as a quality flag, not a guarantee.

The pipeline continues after any per-file failure — it does not abort on individual file errors.

### Manifest schema

When using a JSONL manifest, each line must be a JSON object with:

```json
{
  "path": "relative/or/absolute/path/to/file.py",
  "source": "BugsInPy",
  "license": "MIT"
}
```

- `path`: resolved relative to the manifest file's directory if not absolute.
- `source` and `license`: required; propagated verbatim to the output record.

### CLI

```bash
# Annotate a directory (Tier 1 fields, 1 worker)
python dataset_annotator.py /data/bugsinpy/buggy/ -o bugsinpy_buggy.jsonl --source BugsInPy --license MIT

# Annotate from a JSONL manifest (per-file source/license metadata)
python dataset_annotator.py manifest.jsonl -o annotated.jsonl

# Skip pylint for speed (3-5x faster); pylint_score emitted as null
python dataset_annotator.py /data/tssb/ -o tssb.jsonl --no-pylint

# Full schema including Tier 2 LCOM/CBO fields
python dataset_annotator.py /data/bugsinpy/ -o full.jsonl --full

# Parallel processing (recommended for large datasets)
python dataset_annotator.py /data/tssb/ -o tssb.jsonl --workers 8

# Limit to first N files (useful for test runs)
python dataset_annotator.py /data/tssb/ -o sample.jsonl --limit 1000

# Custom per-tool timeout (default 30s)
python dataset_annotator.py /data/bugsinpy/ -o out.jsonl --tool-timeout 60
```

### Impact

- **New file:** `dataset_annotator.py`
- **New tests:** `tests/test_dataset_annotator.py` (schema validation, Tier 1/2 fields, null on tool skip, error handling, score passthrough)
- **New required dependency:** `complexipy` (add to `requirements.txt`)
- **New optional dependency:** `lcom` (for `--full` mode; document separately, not in `requirements.txt`)
- **Makefile:** add `dataset_annotator.py` and `tests/test_dataset_annotator.py` to lint scope
- **CLAUDE.md:** add usage note
- **`code_analyzer.py`:** no changes; scoring formula reimplemented as standalone functions in `dataset_annotator.py` (not imported — instance method / dataclass coupling)
- **`code_reporter.py`:** no changes

## Open Questions

1. **Manifest format**: JSONL assumed. Should CSV manifests also be supported?
2. **Progress bar**: Rich progress display for long-running batches? Nice-to-have for a follow-up CHG.
3. **inspect4py integration**: HUA-2112 recommends inspect4py for AST/CFG/call-graph metadata. Deferred to a follow-up CHG for Tier 2 structural expansion.

---

## Review

### Round 1 (v1–v5, engineering review)
- [x] Reviewer 1 (Codex): 9.7 / 10 — APPROVED (v5, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9.0 / 10 — APPROVED (v2, 2026-03-22)

### Round 2 (v6–v7, research methodology review)
- [x] External review: 8.6/10 → 9.2/10 (two rounds)
- [x] Reviewer 1 (Codex): 9.5 / 10 — APPROVED (v10, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9.0 / 10 — APPROVED (v9→v10 fix, 2026-03-22)
- [x] Re-approved on: 2026-03-22

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v10: Removed all stale CodeAnalyzer references from failure contract; per-tool timeout records in tool_errors (not error_type); analysis_config field table includes tool_timeout; runtime_env emitted per-record (no batch header ambiguity) | Claude Code |
| 2026-03-22 | v9: Scoring formula reimplemented as standalone functions (not imported from CodeAnalyzer — instance method/CodeMetrics coupling); test suite must verify parity with CodeAnalyzer scoring | Claude Code |
| 2026-03-22 | v8: External review round 2 (9.2/10) — architecture rewrite: DatasetAnnotator runs tools directly (not via CodeAnalyzer) for isolation/timeout/per-tool error; conditional startup validation (--no-pylint skips pylint check); per-tool tool_errors dict replacing single error_type for partial failures; content_sha256 null only on I/O error (not analysis failures); runtime_env metadata (python_version, platform, isolated); isolated flag in class signature | Claude Code |
| 2026-03-22 | v7: Fixed suspect:radon heuristic field name (max_cyclomatic_complexity→cyclomatic_complexity); clarified error_type enum (tool_missing=startup, suspected_silent_failure=data_warnings only); added tool_timeout to class signature and CLI | Claude Code |
| 2026-03-22 | v6: External research review (8.6/10) — added reproducibility metadata (schema_version, annotator_version, tool_versions, content_sha256, analysis_config); tool config isolation (--isolated flags for ruff/mypy/pylint/bandit); per-tool timeout + error taxonomy (error_type/error_detail replacing error); score/grade methodology caveat (derived labels, not ground-truth); AST metric formal definitions table; mypy_env heuristic for environment-sensitive false positives | Claude Code |
| 2026-03-22 | v5: Reframed data_warnings as best-effort diagnostic (not a guarantee); enumerated exact heuristics (suspect:radon, suspect:pylint, suspect:mypy); removed overstatement from failure contract prose | Claude Code |
| 2026-03-22 | v4: Added data_warnings field (stdout capture + heuristic zero-check) to surface swallowed per-tool failures; data_warnings added to Tier 1 schema and field notes | Claude Code |
| 2026-03-22 | v3: Fixed Layer 1 CodeMetrics→output field mapping table (avg_complexity moved to Layer 2, renames for overall_score/functions_analyzed/max_cyclomatic_complexity); added two-phase failure contract (startup validation + ast.parse check before CodeAnalyzer); added essential_complexity omission rationale | Claude Code |
| 2026-03-22 | v2: Rewrote architecture to honest two-layer model; removed essential_complexity (not in radon API); fixed complexipy as always-required; defined null semantics for --no-pylint; added --workers and --limit flags; added manifest schema section | Claude Code |
| 2026-03-22 | v1: Schema revised per HUA-2111/HUA-2112: added cognitive_complexity, essential_complexity, raw Halstead counts, fanout split, Tier 2 LCOM/CBO fields, --full flag; demoted halstead_bugs | Claude Code |
| 2026-03-21 | Initial version | Claude Code |
