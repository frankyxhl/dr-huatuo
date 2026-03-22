# PRP-2124: Unified CLI and Report Integration

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Related:** HUA-2122-PRP (Quality Profile), HUA-2109-PRP (Annotator)
**Reviewed by:** —

---

## Background

Huatuo currently has 7 standalone Python scripts, each with its own CLI:

| Script | Purpose | Typical usage |
|---|---|---|
| `code_analyzer.py` | Single-file analysis + score | `python code_analyzer.py file.py` |
| `code_reporter.py` | Project report (terminal/HTML/JSON/MD) | `python code_reporter.py . -f html -o report.html` |
| `dataset_annotator.py` | Batch annotation for ML datasets | `python dataset_annotator.py dir/ -o out.jsonl` |
| `dataset_dedup.py` | Near-duplicate detection | `python dataset_dedup.py in.jsonl -o out.jsonl` |
| `bugsinpy_extract.py` | BugsInPy data extraction | `python bugsinpy_extract.py --project thefuck` |
| `bugsinpy_analysis.py` | BugsInPy validation analysis | `python bugsinpy_analysis.py --project thefuck` |
| `scoring_optimizer.py` | Scoring weight optimization | `python scoring_optimizer.py --lopo` |
| `quality_profile.py` | 5-dimension quality rating | _(library only, no CLI)_ |

A developer wanting to check their code's health has to know which script to use. The quality profile (HUA-2122) — huatuo's newest and most actionable output — has no CLI at all.

---

## What Is It?

A unified `huatuo` CLI entry point that consolidates the most common user-facing operations into one command, and integrates the quality profile into existing report outputs.

---

## Problem

### 1. No single entry point

A new user has to discover 7+ scripts. The most common operation — "check my code's quality" — requires knowing about both `code_analyzer.py` (single file) and `code_reporter.py` (project), neither of which includes the quality profile.

### 2. Quality profile is disconnected from reports

`quality_profile.py` is a library with no CLI. Its output only appears in `dataset_annotator.py`'s JSONL — not in the terminal, HTML, or Markdown reports that `code_reporter.py` generates.

### 3. No CI/CD integration path

To use huatuo in CI, you'd have to write custom scripts to invoke `code_analyzer.py` or `code_reporter.py` and parse their output. No exit-code-based quality gate exists.

---

## Scope

**In scope (v1):**
- `cli.py` with subcommands (`check`, `report`, `version`)
- `check <path>` — analyze file(s) using `CodeAnalyzer` + Layer 2 metrics + `quality_profile.py`, show quality profile, exit code via `--fail-on`
- `report <path>` — delegates to existing `code_reporter.py` (no quality profile integration in v1)
- `version` — show version and tool versions
- Quality gate: `--fail-on` flag with Security interaction

**Out of scope (v1 — follow-up CHGs):**
- Quality profile integration into `code_reporter.py` reports (requires `FileMetrics` extension)
- `python -m huatuo` / pip-installable CLI (requires package restructure)
- Replacing existing scripts (kept for backward compatibility)
- GitHub Action / pre-commit hook
- Dataset annotation commands in unified CLI
- Configuration file for custom thresholds

---

## Proposed Solution

### CLI design

```bash
# Quick check — shows quality profile for a single file
huatuo check example_code.py

# Output:
# example_code.py
#   Maintainability: A  (MI=65.3)
#   Complexity:      D  (cognitive_complexity=28 > 25)
#   Code Style:      C  (ruff_violations=5)
#   Documentation:   C  (docstring_density=0.25)
#   Security:        PASS
#
#   Action items:
#     1. Complexity: reduce cognitive complexity (28 → ≤25 for C, ≤15 for B)
#     2. Code Style: fix 5 ruff violations (0 for A)


# Project check — shows summary for all files
huatuo check src/

# Output:
# Analyzed 12 files
#
# Project Quality Summary:
#   Maintainability: 8A 3B 1C
#   Complexity:      2A 5B 3C 2D
#   Code Style:      11A 1B
#   Documentation:   1A 4B 5C 2D
#   Security:        12 PASS
#
# Files with issues (D-rated dimensions):
#   src/parser.py      Complexity: D (cognitive=32)
#   src/renderer.py    Complexity: D (cognitive=28)
#   src/renderer.py    Documentation: D (docstring_density=0.10)


# Full report with quality profile
huatuo report src/ -f html -o report.html
huatuo report src/ -f terminal
huatuo report src/ -f json -o report.json
huatuo report src/ -f markdown -o report.md


# CI quality gate — exit 1 if any file has a D in any dimension
huatuo check src/ --fail-on D

# Stricter gate — exit 1 if any file has C or worse
huatuo check src/ --fail-on C

# Gate on specific dimension only
huatuo check src/ --fail-on D --dimension security
# (exits 1 only if security is FAIL)


# Version info
huatuo version
# huatuo 0.2.0
# Tools: ruff 0.15.7, radon 6.0.1, bandit 1.9.4, mypy 1.19.1, pylint 4.0.5, complexipy 5.2.0
```

### Architecture

```
cli.py
  ├── check    → CodeAnalyzer (5-tool metrics) + _gather_layer2() + quality_profile.py
  ├── report   → code_reporter.py (existing, no quality profile in v1)
  └── version  → tool version detection
```

**Metrics gap resolution:** `CodeMetrics` from `code_analyzer.py` only provides 5 of the 13 fields `quality_profile.py` needs. The CLI bridges this gap with a `_gather_layer2(path)` function that computes the missing fields:

| Missing field | Source | Method |
|---|---|---|
| `maintainability_index` | radon | `mi_visit(src, multi=True)` |
| `cognitive_complexity` | complexipy | `complexipy.file_complexity(path)` |
| `max_nesting_depth` | AST | Walk `ast.parse(src)`, count nested control-flow |
| `docstring_density` | AST | Count functions with docstrings / total functions |
| `comment_density` | text | Count `#`-lines / total lines |
| `loc` | text | `len(source.splitlines())` |
| `function_count` | AST | Count `ast.FunctionDef` + `ast.AsyncFunctionDef` nodes |
| `class_count` | AST | Count `ast.ClassDef` nodes |
| `data_warnings` | — | Defaults to `[]` (no heuristic checks in CLI mode; full checks only in `dataset_annotator.py`) |

These are the same computations as `dataset_annotator.py` Layer 2, but without isolation flags, tool_errors, content_sha256, or JSONL output. The functions are simple (5–15 lines each) and implemented directly in `cli.py` — no shared module needed, no changes to existing scripts.

**Field mapping:** `CodeMetrics.max_cyclomatic_complexity` → mapped to `cyclomatic_complexity` for quality_profile compatibility. `CodeMetrics.functions_analyzed` → mapped to `function_count`.

**Report integration deferred to v2.** `code_reporter.py` uses its own `FileMetrics` dataclass which also lacks the Layer 2 fields. Integrating quality profile into reports requires either extending `FileMetrics` or refactoring the reporter — this is a separate CHG. v1 only adds `huatuo check` (quality profile) and `huatuo report` (delegates to existing `code_reporter.py` unchanged).

### Entry point

```python
# cli.py (or __main__.py)
import argparse
from code_analyzer import CodeAnalyzer
from quality_profile import profile_file

def cmd_check(args):
    analyzer = CodeAnalyzer()
    for file in discover_files(args.path, args.exclude):
        metrics = analyzer.analyze(file)
        profile = profile_file(metrics.to_dict())
        render_profile(file, profile)

    if args.fail_on:
        # Check quality gate
        if any_dimension_at_or_below(profiles, args.fail_on, args.dimension):
            sys.exit(1)

def cmd_report(args):
    # Delegate to existing code_reporter with quality_profile integration
    ...
```

### Quality gate logic

`--fail-on <grade>` sets the minimum acceptable rating:

| Flag | Exits non-zero if... |
|---|---|
| `--fail-on D` | Any file has at least one D-rated dimension |
| `--fail-on C` | Any file has at least one C or D-rated dimension |
| `--fail-on B` | Any file has anything below A |
| `--fail-on FAIL` | Any file has Security: FAIL |
| `--fail-on WARN` | Any file has Security: WARN or FAIL |

**Security + grade interaction:** `--fail-on D` implicitly includes Security FAIL (since FAIL is worse than any D). `--fail-on C` includes both Security FAIL and WARN. This avoids surprising behavior where a Security FAIL passes a `--fail-on D` gate.

`--dimension <name>` narrows the gate to a single dimension. Without it, all dimensions are checked.

### Report integration (v2 — NOT in v1)

> The following is deferred to a follow-up CHG. v1's `report` subcommand delegates to `code_reporter.py` unchanged.

Quality profile in reports requires extending `code_reporter.py`'s `FileMetrics` to include Layer 2 fields — a separate architectural change. Future v2 would add:
- Terminal: colored quality profile box via `rich`
- HTML: colored A/B/C/D badges per dimension
- JSON: `quality_profile` key per file
- Markdown: quality profile table per file

### Entry point (v1)

```bash
# v1: run cli.py directly (no package restructure needed)
python cli.py check .
python cli.py report . -f terminal
python cli.py version
```

The project is currently flat scripts in the root directory (no `huatuo/` package). v1 keeps this structure — `cli.py` is just another script. Restructuring into a `huatuo/` package with `__main__.py` for `python -m huatuo` is a follow-up CHG.

### Dependencies

Uses existing modules and tools already in the venv:
- `code_analyzer.py`, `quality_profile.py` (project modules)
- `rich` (terminal rendering, already installed)
- `radon` (MI computation via `mi_visit`, already installed for `code_analyzer.py`)
- `complexipy` (cognitive complexity, already installed for `dataset_annotator.py`)
- `argparse` (stdlib)

No NEW dependencies — all are already required by existing scripts.

### Impact

- **New file:** `cli.py`
- **New tests:** `tests/test_cli.py` (subcommand routing, quality gate exit codes, dimension filtering, file discovery, Layer 2 metrics gathering)
- **No modifications to existing scripts** — `code_analyzer.py`, `code_reporter.py`, `quality_profile.py` all unchanged
- **Makefile:** add `cli.py` to `lint` and `fmt`
- **CLAUDE.md:** add `python cli.py check/report/version` usage

---

## Open Questions

_All open questions resolved before review._

1. **Why `huatuo check` uses `code_analyzer.py` not `dataset_annotator.py`?** The annotator is designed for research: isolation flags, tool_errors, content_sha256, JSONL batch output. `check` is for developers: fast, simple, human-readable. Using the simpler `code_analyzer.py` keeps it lightweight. The quality profile works on both — it just needs the metric dict.

2. **Why not replace existing scripts?** Backward compatibility. Users of `code_analyzer.py` and `code_reporter.py` shouldn't be broken. The unified CLI is additive.

3. **Why `--fail-on` instead of a numeric threshold?** The quality profile deliberately avoids numeric scores. `--fail-on D` is clear: "fail if anything is rated D." This matches the multi-dimensional philosophy — you gate on the dimension rating, not a number.

4. **How does `huatuo check` handle `code_analyzer.py`'s `CodeMetrics` vs `quality_profile.py`'s expected dict?** `CodeMetrics.to_dict()` produces a dict with field names matching the quality profile's expected keys (`maintainability_index`, `cyclomatic_complexity`, etc.). Note: `code_analyzer.py` uses `max_cyclomatic_complexity` — the CLI maps this to `cyclomatic_complexity` for consistency with the quality profile. `cognitive_complexity` and `max_nesting_depth` are not in `CodeMetrics` and must be computed additionally (via radon and AST, same as `dataset_annotator.py` Layer 2 but without isolation flags).

5. **What about files that fail to parse?** Same as `code_analyzer.py` behavior: print error, continue to next file. Quality profile dimensions default to N/A for unparseable files. `--fail-on` does not trigger on N/A.

---

## Review

- [x] Reviewer 1 (Codex): 9 / 10 — APPROVED (v1, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9 / 10 — APPROVED (v3, 2026-03-22)
- [x] Approved on: 2026-03-22

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v3: Report integration section marked v2 future; removed code_reporter.py from Impact; added data_warnings to Layer 2 table; acknowledged complexipy in Dependencies | Claude Code |
| 2026-03-22 | v2: Fixed metrics gap (explicit _gather_layer2 with 8 missing fields); report integration deferred to v2 CHG; entry point is python cli.py (no package restructure); Security+grade interaction defined | Claude Code |
| 2026-03-22 | v1: Initial version | Claude Code |
