# PRP-2129: Multi-Language Analyzer Plugin Architecture

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Draft
**Related:** HUA-2122-PRP (Quality Profile), HUA-2124-PRP (Unified CLI)
**Reviewed by:** —

---

## Background

dr-huatuo currently only analyzes Python files. The quality framework — 5-dimension quality profile, CLI, HTML reports, quality gate — is conceptually language-agnostic, but the implementation hardcodes Python-specific tools (ruff, radon, bandit, mypy, pylint, complexipy) throughout.

The user wants `ht check src/` to work on **any language** — Python, JavaScript, TypeScript, Go, Rust, Java, etc. — with the same quality profile output.

This PRP proposes a plugin architecture that separates the language-specific analysis layer from the language-agnostic quality framework.

---

## What Is It?

A `LanguageAnalyzer` protocol (interface) that each language implements. The framework auto-detects file language, dispatches to the correct analyzer, and produces the same quality profile regardless of language.

---

## Problem

### 1. Python tools are hardcoded everywhere

`code_analyzer.py` calls `ruff`, `radon`, `bandit`, `mypy`, `pylint` directly. `cli.py` imports from `code_analyzer` and calls radon/complexipy in `_gather_layer2()`. Adding JS support would mean duplicating all this wiring.

### 2. Quality dimensions are language-agnostic

McCabe cyclomatic complexity, maintainability index, cognitive complexity, nesting depth, comment density, docstring coverage — these concepts exist in every language. Only the **tools** that compute them differ.

### 3. No language detection

`ht check src/` currently assumes all `.py` files. A mixed-language project (Python backend + TypeScript frontend) needs automatic file-type routing.

---

## Scope

**In scope:**
- `LanguageAnalyzer` protocol definition (the interface contract)
- Refactor existing Python analysis into `PythonAnalyzer` implementing the protocol
- Language auto-detection by file extension
- `TypeScriptAnalyzer` as the first non-Python language (.ts, .tsx)
- `ht check` works on mixed Python + TypeScript projects
- Quality profile and reports work unchanged for all languages

**Out of scope (v1):**
- JavaScript-only analyzer (TypeScript tools handle .js too if needed; separate JS analyzer deferred)
- Go, Rust, Java analyzers (follow-up CHGs)
- Custom analyzer plugin loading from external packages
- Per-language quality profile threshold customization
- Language-specific report sections

---

## Proposed Solution

### The Protocol

```python
# src/dr_huatuo/analyzers/base.py

from typing import Protocol
from pathlib import Path

class LanguageAnalyzer(Protocol):
    """Interface that every language analyzer must implement."""

    name: str                    # e.g., "python", "javascript", "typescript"
    extensions: list[str]        # e.g., [".py"], [".js", ".jsx"], [".ts", ".tsx"]

    def check_tools(self) -> dict[str, str | None]:
        """Verify required tools are available.

        Returns: {tool_name: version_string} for available tools,
                 {tool_name: None} for missing tools.
        Raises if critical tools are missing.
        """
        ...

    def analyze_file(self, path: Path) -> dict:
        """Analyze a single file and return the standard metric dict.

        Returns a dict with ALL of these keys (null if not computable):
            # Complexity
            cyclomatic_complexity: int | None
            avg_complexity: float | None
            cognitive_complexity: int | None
            max_nesting_depth: int | None

            # Volume
            loc: int | None
            function_count: int | None
            class_count: int | None

            # Readability
            maintainability_index: float | None
            comment_density: float | None
            docstring_density: float | None

            # Code style
            lint_violations: int | None       # ruff (Python), eslint (JS/TS)
            linter_score: float | None        # pylint (Python), null for others

            # Security
            security_high: int | None         # bandit (Python), eslint-plugin-security (JS)
            security_medium: int | None

            # Type safety
            type_errors: int | None           # mypy (Python), tsc (TS), null for JS

            # Halstead (optional — null if tool doesn't support)
            n1: int | None
            n2: int | None
            N1: int | None
            N2: int | None
            halstead_volume: float | None
            halstead_difficulty: float | None
            halstead_effort: float | None

            # Metadata
            language: str                     # "python", "javascript", etc.
            data_warnings: list[str]
            error_type: str | None
            error_detail: str | None
            tool_errors: dict | None
        """
        ...
```

### Standard Metric Schema (language-neutral field names)

The current Python-specific field names are renamed to generic names:

| Current (Python-only) | New (language-neutral) | Notes |
|---|---|---|
| `ruff_violations` | `lint_violations` | ruff (Py), eslint (JS/TS), golint (Go) |
| `pylint_score` | `linter_score` | pylint (Py); null for languages without a second linter |
| `bandit_high` | `security_high` | bandit (Py), eslint-plugin-security (JS) |
| `bandit_medium` | `security_medium` | Same |
| `mypy_errors` | `type_errors` | mypy (Py), tsc (TS), null for JS |

Other metrics keep their names — they are already language-neutral (`cyclomatic_complexity`, `loc`, `maintainability_index`, etc.).

**Backward compatibility:** `PythonAnalyzer` also emits the old field names (`ruff_violations`, `pylint_score`, etc.) alongside the new ones, so existing consumers don't break.

### Language Detection

```python
# src/dr_huatuo/analyzers/registry.py

ANALYZERS: dict[str, type[LanguageAnalyzer]] = {}

def register(analyzer_class: type[LanguageAnalyzer]) -> None:
    for ext in analyzer_class.extensions:
        ANALYZERS[ext] = analyzer_class

def get_analyzer(path: Path) -> LanguageAnalyzer | None:
    return ANALYZERS.get(path.suffix)

# Auto-register built-in analyzers
register(PythonAnalyzer)     # .py
register(TypeScriptAnalyzer) # .ts, .tsx
```

### Directory Structure

```
src/dr_huatuo/
├── analyzers/
│   ├── __init__.py          # registry + auto-detection
│   ├── base.py              # LanguageAnalyzer protocol
│   ├── python.py            # PythonAnalyzer (refactored from existing code)
│   └── typescript.py        # TypeScriptAnalyzer (.ts, .tsx)
├── cli.py                   # unchanged API; uses registry internally
├── quality_profile.py       # unchanged; works on any metric dict
├── code_reporter.py         # unchanged
└── ...
```

### JS/TS Analyzer: Tool Mapping

| Metric | Python tool | JS/TS tool | Package |
|---|---|---|---|
| `lint_violations` | ruff | **eslint** | `npm install eslint` |
| `linter_score` | pylint | _(null)_ | — |
| `security_high/medium` | bandit | **eslint-plugin-security** | eslint plugin |
| `type_errors` | mypy | **tsc --noEmit** (TS only) | typescript |
| `cyclomatic_complexity` | radon cc | **escomplex** | `npm install typhonjs-escomplex` |
| `avg_complexity` | radon cc | escomplex | Same |
| `cognitive_complexity` | complexipy | **eslint-plugin-sonarjs** | eslint plugin |
| `maintainability_index` | radon mi | escomplex | Same |
| `max_nesting_depth` | AST walk | **eslint max-depth rule** or AST | — |
| `loc` | line count | line count | — |
| `function_count` | AST | AST (babel/ts-parser) | — |
| `class_count` | AST | AST | — |
| `comment_density` | text analysis | text analysis | — |
| `docstring_density` | AST (Python docstrings) | **JSDoc coverage** | — |
| Halstead | radon hal | escomplex | Same |

### Quality Profile Compatibility

`quality_profile.py` reads generic field names. The mapping:

| Quality Profile reads | Analyzer provides |
|---|---|
| `maintainability_index` | Same name, all languages |
| `cognitive_complexity` | Same name, all languages |
| `max_nesting_depth` | Same name, all languages |
| `ruff_violations` → `lint_violations` | Update quality_profile to read `lint_violations` |
| `pylint_score` → `linter_score` | Update, null-safe (JS has no second linter) |
| `bandit_high` → `security_high` | Update |
| `mypy_errors` → `type_errors` | Update, null-safe (JS has no type checker) |
| `docstring_density` | Same name; JS uses JSDoc coverage |
| `comment_density` | Same name, all languages |

### CLI Changes

```bash
# Unchanged — auto-detects language
ht check src/

# Output now shows language per file:
# src/app.ts (TypeScript)
#   Maintainability    A  (MI=72.1)
#   Complexity         B  (cognitive=12)
#   Code Style         A  (eslint=0)
#   Documentation      C  (jsdoc=35%)
#   Security           PASS
#   Type Safety        3 tsc errors
#
# src/utils.py (Python)
#   Maintainability    B  (MI=45.3)
#   ...

# Filter by language
ht check src/ --language python
ht check src/ --language typescript
```

### Implementation Phases

| Phase | What | Effort |
|---|---|---|
| **Phase 1** | Define `LanguageAnalyzer` protocol + registry + auto-detection | Small |
| **Phase 2** | Refactor existing Python code into `PythonAnalyzer` | Medium — move code, update imports |
| **Phase 3** | Rename Python-specific fields to generic names + backward compat | Small |
| **Phase 4** | Update `quality_profile.py` and `cli.py` to use generic names | Small |
| **Phase 5** | Implement `TypeScriptAnalyzer` | Medium — new tool integrations |
| **Phase 6** | Test on real mixed-language projects | Small |

Phases 1–4 are refactoring (no new features, existing tests must pass). Phase 5 is new functionality. Each phase is a separate CHG.

### Dependencies

| Language | Required tools | Install |
|---|---|---|
| Python | ruff, radon, bandit, mypy, pylint, complexipy | `pip install dr-huatuo` |
| JS/TS | Node.js, eslint, escomplex | `npm install -g eslint typhonjs-escomplex` |
| TS only | typescript | `npm install -g typescript` |

`ht check` gracefully handles missing tools: if eslint is not installed and you check a `.js` file, it reports `"eslint not found — install with npm install -g eslint"` instead of crashing.

### Impact

- **New directory:** `src/dr_huatuo/analyzers/` (base, registry, python, typescript)
- **Refactored:** `cli.py` (use registry instead of direct imports), `quality_profile.py` (generic field names)
- **Backward compatible:** Python-specific field names still emitted alongside generic names
- **New npm dependencies** for JS/TS (not Python deps — separate tool chain)

---

## Open Questions

_All open questions resolved before review._

1. **Why not write the JS/TS analyzer in JavaScript/TypeScript?** Keeping everything in Python simplifies the build, packaging, and distribution. The JS/TS tools (eslint, escomplex, tsc) are invoked via `subprocess.run()` just like the Python tools. Users need Node.js installed, but dr-huatuo itself stays a pure Python package.

2. **Why a Protocol instead of an ABC?** Protocol (structural typing) allows third-party analyzers to implement the interface without importing dr-huatuo. An external package can define `class RustAnalyzer` that happens to have the right methods and register it. ABC would require inheritance.

3. **Why rename fields?** `ruff_violations` is meaningless for TypeScript. `lint_violations` is universal. Backward compat is maintained by emitting both names for Python.

4. **What about languages with no MI/Halstead tool?** Fields are nullable. If escomplex doesn't exist for a language, `maintainability_index` is `null` and the Maintainability dimension returns N/A. The quality profile already handles null dimensions.

5. **What about monorepos with many languages?** `ht check .` walks the directory, detects language per file, routes to the correct analyzer, and aggregates results. The project summary groups files by language. `--language` flag filters if you only want one.

6. **How does docstring_density work for JS/TS?** JSDoc comments (`/** ... */`) are the equivalent of Python docstrings. `docstring_density` = functions with JSDoc / total functions. Same metric, different syntax.

---

## Review

- [ ] Reviewer 1 (Codex): score ≥ 9
- [ ] Reviewer 2 (Gemini): score ≥ 9
- [ ] Approved on: —

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Claude Code |
