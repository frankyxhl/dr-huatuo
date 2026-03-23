# PRP-2129: Multi-Language Analyzer Plugin Architecture

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Approved
**Related:** HUA-2122-PRP (Quality Profile), HUA-2124-PRP (Unified CLI)
**Affected SOPs:** HUA-2104 (Workflow Routing PRJ — branches 2, 3, 6 need updating for multi-language)
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

`code_analyzer.py` calls `ruff`, `radon`, `bandit`, `mypy`, `pylint` directly. `cli.py` imports from `code_analyzer` and calls `radon`/`complexipy` as Python API calls (not subprocess) in `_gather_layer2()`. `code_reporter.py` has its own separate `CodeAnalyzer` class that also hardcodes the same Python tools. `dataset_annotator.py` similarly imports `radon` and `complexipy` as Python APIs. Adding JS support would mean duplicating all this wiring in every consumer.

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
- Field rename from Python-specific to generic names in all core modules: `code_analyzer.py`, `code_reporter.py`, `cli.py`, `quality_profile.py`
- Update `CodeMetrics` and `FileMetrics` dataclasses to use generic field names (with deprecated aliases for backward compat)
- Update all test files to use generic field names (394 references across 9 test files)

**Out of scope (v1):**
- JavaScript-only analyzer (TypeScript tools handle .js too if needed; separate JS analyzer deferred)
- Go, Rust, Java analyzers (follow-up CHGs)
- Custom analyzer plugin loading from external packages
- Per-language quality profile threshold customization
- Language-specific report sections
- `dataset_annotator.py` field rename (32 references) — research module, will be updated in a follow-up CHG after the core rename stabilizes
- `scoring_optimizer.py` field rename (30 references) — research module, same follow-up
- `bugsinpy_analysis.py` field rename (5 references) — research module, same follow-up
- `code_reporter.py`'s own `CodeAnalyzer` class: remains Python-only in v1; refactoring it to use the plugin registry is deferred to a follow-up PRP (the reporter's analyzer is tightly coupled to its own `FileMetrics` dataclass and rendering pipeline)

---

## Proposed Solution

### The Protocol

```python
# src/dr_huatuo/analyzers/base.py

from typing import ClassVar, Protocol
from pathlib import Path

class LanguageAnalyzer(Protocol):
    """Interface that every language analyzer must implement.

    Analyzers may invoke tools via subprocess OR as in-process Python API
    calls (e.g., PythonAnalyzer calls radon and complexipy as libraries).
    The protocol is agnostic to the invocation method.
    """

    name: ClassVar[str]              # e.g., "python", "typescript"
    extensions: ClassVar[list[str]]  # e.g., [".py"], [".ts", ".tsx"]
    # Which tools are critical (raise on missing) vs optional (degrade gracefully)
    critical_tools: ClassVar[list[str]]
    optional_tools: ClassVar[list[str]]

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialize with optional project root for tools that need context.

        project_root is required by TypeScript tools (tsc needs tsconfig.json,
        eslint needs .eslintrc). Python tools work per-file and ignore this.
        """
        ...

    def check_tools(self) -> dict[str, str | None]:
        """Verify required tools are available.

        Returns: {tool_name: version_string} for available tools,
                 {tool_name: None} for missing tools.
        Raises ToolNotFoundError if any tool in critical_tools is missing.
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
            language: str                     # "python", "typescript", etc.
            data_warnings: list[str]
            error_type: str | None
            error_detail: str | None
            tool_errors: dict | None
        """
        ...

    def analyze_batch(self, paths: list[Path]) -> list[dict]:
        """Analyze multiple files in a single invocation.

        Default implementation calls analyze_file() per file.
        Override for languages where tools have high startup cost
        (e.g., Node.js-based tools like eslint, tsc, escomplex).

        TypeScriptAnalyzer overrides this to run eslint/tsc/escomplex
        once on all files, then split results per file — avoiding
        Node.js startup overhead per file.

        Returns: list of metric dicts, one per input path, same order.
        """
        ...
```

**Critical vs optional tools per language:**

| Language | Critical (raise if missing) | Optional (degrade gracefully) |
|---|---|---|
| Python | ruff, radon, bandit, mypy | pylint, complexipy |
| TypeScript | eslint, typescript (tsc) | escomplex, eslint-plugin-security, eslint-plugin-sonarjs |

**Invocation patterns (not all tools are subprocesses):**

| Tool | Invocation | Notes |
|---|---|---|
| ruff, bandit, mypy, pylint | subprocess | JSON output parsed |
| radon | Python API (`from radon.metrics import mi_visit`) | Used in `cli.py` and `dataset_annotator.py` |
| complexipy | Python API (`from complexipy import file_complexity`) | Used in `cli.py` and `dataset_annotator.py` |
| eslint, tsc, escomplex | subprocess | Node.js tools, JSON output parsed |

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

**Backward compatibility strategy:**

The field rename touches 549 references across 16 files. The migration strategy:

1. **Dataclasses (`CodeMetrics`, `FileMetrics`):** Rename fields to generic names (`lint_violations`, `security_high`, etc.). Add `@property` aliases for old names (`ruff_violations`, `bandit_high`, etc.) that emit `DeprecationWarning` and delegate to the new field. This keeps dataclass construction using new names while existing consumers (tests, research modules) continue to work via the properties.

2. **Core modules (in-scope):** `code_analyzer.py`, `cli.py`, `quality_profile.py` — update to use new field names directly. `code_reporter.py`'s `FileMetrics` dataclass gets the same treatment.

3. **Test files (in-scope, 394 refs across 9 files):** Migrate to new field names in Phase 3 via automated find-and-replace with `make test` verification after each file.

4. **Research modules (out-of-scope):** `dataset_annotator.py` (32 refs), `scoring_optimizer.py` (30 refs), `bugsinpy_analysis.py` (5 refs) — continue using deprecated property aliases until a follow-up CHG migrates them.

5. **`PythonAnalyzer.analyze_file()` dict output:** Emits both old and new field names in the returned dict, so any dict-based consumers (quality profile, CLI) work with either name during transition.

### Language Detection

```python
# src/dr_huatuo/analyzers/registry.py

ANALYZERS: dict[str, type[LanguageAnalyzer]] = {}

def register(analyzer_class: type[LanguageAnalyzer]) -> None:
    for ext in analyzer_class.extensions:
        ANALYZERS[ext] = analyzer_class

def get_analyzer_class(ext: str) -> type[LanguageAnalyzer] | None:
    """Return the analyzer CLASS for a file extension, or None."""
    return ANALYZERS.get(ext)

def create_analyzer(path: Path, project_root: Path | None = None) -> LanguageAnalyzer | None:
    """Create an analyzer INSTANCE for a file, or None if unsupported."""
    cls = ANALYZERS.get(path.suffix)
    if cls is None:
        return None
    return cls(project_root=project_root)

# Auto-register built-in analyzers
register(PythonAnalyzer)     # .py
register(TypeScriptAnalyzer) # .ts, .tsx
```

The registry stores **classes**. `create_analyzer()` instantiates with `project_root` (needed by `TypeScriptAnalyzer` for `tsconfig.json` / `.eslintrc` resolution; ignored by `PythonAnalyzer`).

### Directory Structure

```
src/dr_huatuo/
├── analyzers/
│   ├── __init__.py          # registry + auto-detection
│   ├── base.py              # LanguageAnalyzer protocol + ToolNotFoundError
│   ├── python.py            # PythonAnalyzer (refactored from code_analyzer.py)
│   └── typescript.py        # TypeScriptAnalyzer (.ts, .tsx)
├── cli.py                   # uses registry; _gather_layer2() delegates to analyzer
├── quality_profile.py       # updated to read generic field names (null-safe)
├── code_analyzer.py         # updated: CodeMetrics uses generic fields + deprecated aliases
├── code_reporter.py         # FileMetrics uses generic fields + deprecated aliases;
│                            #   own CodeAnalyzer class stays Python-only (v1)
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

| Phase | What | Effort | Notes |
|---|---|---|---|
| **Phase 1** | Define `LanguageAnalyzer` protocol + registry + auto-detection | Small | New files only, no existing code changes |
| **Phase 2** | Refactor `code_analyzer.py` Python analysis into `PythonAnalyzer`; `cli.py`'s `_gather_layer2()` and `_build_metrics_dict()` delegate to `PythonAnalyzer` instead of direct radon/complexipy API calls | Medium | `_build_metrics_dict()` is replaced by the analyzer's `analyze_file()` dict output |
| **Phase 3** | Rename Python-specific fields to generic names in `CodeMetrics`, `FileMetrics`, and all 9 test files (394 refs) + add deprecated `@property` aliases | Medium | Automated find-and-replace with `make test` verification per file; research modules use aliases |
| **Phase 4** | Update `quality_profile.py` and `cli.py` to read generic field names | Small | Null-safe for fields that JS/TS may not provide (e.g., `linter_score`) |
| **Phase 5** | Implement `TypeScriptAnalyzer` with batch processing via `analyze_batch()` | Medium-Large | New tool integrations; requires Node.js in CI |
| **Phase 6** | Test on real mixed-language projects | Small | Integration testing |

Phases 1–4 are refactoring (no new features, existing tests must pass). Phase 5 is new functionality. Each phase is a separate CHG.

**Phase 2 detail — `_build_metrics_dict()` evolution:** Currently `cli.py` line 215-238 manually maps `CodeMetrics` fields to a quality-profile-compatible dict. After refactoring, `PythonAnalyzer.analyze_file()` returns the standard metric dict directly, so `_build_metrics_dict()` is no longer needed. `_gather_layer2()` calls `analyzer.analyze_file(path)` (or `analyzer.analyze_batch(paths)` for batch) instead of importing radon/complexipy directly.

### Dependencies

| Language | Required tools | Install |
|---|---|---|
| Python | ruff, radon, bandit, mypy, pylint, complexipy | `pip install dr-huatuo` |
| JS/TS | Node.js, eslint, escomplex | `npm install -g eslint typhonjs-escomplex` |
| TS only | typescript | `npm install -g typescript` |

`ht check` gracefully handles missing tools: if eslint is not installed and you check a `.js` file, it reports `"eslint not found — install with npm install -g eslint"` instead of crashing.

### Impact

**New files:**
- `src/dr_huatuo/analyzers/` — `base.py` (protocol), `__init__.py` (registry), `python.py`, `typescript.py`

**Refactored (in-scope, 16 files total):**
- `code_analyzer.py` — `CodeMetrics` fields renamed + deprecated aliases; `CodeAnalyzer` logic extracted to `PythonAnalyzer`
- `code_reporter.py` — `FileMetrics` fields renamed + deprecated aliases; own `CodeAnalyzer` class stays Python-only (v1)
- `cli.py` — uses registry; `_gather_layer2()` delegates to analyzer; `_build_metrics_dict()` removed
- `quality_profile.py` — reads generic field names (null-safe)
- 9 test files — 394 references migrated to generic field names
- `conftest.py` — fixture field names updated

**Not refactored (out-of-scope, use deprecated aliases):**
- `dataset_annotator.py` (32 refs), `scoring_optimizer.py` (30 refs), `bugsinpy_analysis.py` (5 refs)

**Backward compatible:** deprecated `@property` aliases on dataclasses + dual-emit dict from `PythonAnalyzer`

**New external dependencies:** Node.js + npm packages for JS/TS analysis (see Risk section)

---

## Risks and Trade-offs

### 1. Node.js dependency for a Python package

dr-huatuo is distributed via pip as a pure Python package. Adding TypeScript analysis introduces a hard dependency on Node.js, npm, and several npm packages (eslint, typescript, escomplex). Users who only analyze Python are unaffected — Node.js is only required when `.ts`/`.tsx` files are encountered. **Mitigation:** Graceful degradation with clear error messages ("eslint not found — install with npm install -g eslint"). CI must install Node.js for TypeScript tests; Python-only tests run without it.

### 2. Field rename blast radius (549 references, 16 files)

Renaming `ruff_violations` → `lint_violations` etc. touches 549 locations. A find-and-replace error could break tests silently if field names collide. **Mitigation:** Phase 3 uses automated rename with `make test` verification after each file. Deprecated `@property` aliases catch any missed references at runtime with warnings. Research modules are explicitly out-of-scope and use aliases.

### 3. Three `CodeAnalyzer` classes

After refactoring, three analyzer-like classes will coexist: `PythonAnalyzer` (new, in `analyzers/python.py`), `CodeAnalyzer` in `code_analyzer.py` (legacy, delegates to `PythonAnalyzer`), and `CodeAnalyzer` in `code_reporter.py` (separate, stays Python-only). **Mitigation:** v1 explicitly keeps `code_reporter.py`'s `CodeAnalyzer` independent. A follow-up PRP will address unifying or deprecating the legacy classes. The relationship is documented in the directory structure section.

### 4. Node.js tool startup overhead

Node.js tools (eslint, tsc, escomplex) have ~500ms startup cost per invocation. Running them per-file via subprocess on a 100-file project would take ~50s per tool. **Mitigation:** `analyze_batch()` method runs each Node.js tool once on all files, then splits results per file. eslint and tsc both accept multiple file arguments natively.

### 5. TypeScript project context requirement

`tsc --noEmit` requires `tsconfig.json` to resolve types; eslint needs `.eslintrc` or `eslint.config.js` for rules. Per-file analysis without project context produces incorrect results. **Mitigation:** `TypeScriptAnalyzer.__init__` takes `project_root` parameter. If no config files exist at `project_root`, the analyzer uses sensible defaults (eslint recommended config, tsc strict mode with no path resolution).

### 6. Halstead partial availability across languages

Python files have Halstead data (via radon); TypeScript may not (escomplex support varies). Project-level aggregation mixing null and non-null Halstead data could produce misleading averages. **Mitigation:** Aggregation functions skip null values and report "N/A" when insufficient data. The quality profile already handles null dimensions — no new logic needed, but project summaries must show "Halstead: N/A (TypeScript files excluded)" rather than silently averaging only Python files.

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

- [x] Reviewer 1 (Codex): 9.4/10 PASS (R2)
- [x] Reviewer 2 (Gemini): 9.4/10 PASS (R2)
- [x] Approved on: 2026-03-23

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Claude Code |
| 2026-03-23 | R1 revision: address all 20 blocking issues from Codex (14) and Gemini (6) — add complexipy to problem; enumerate all affected modules in scope; add analyze_batch(); add project_root; define critical/optional tools; fix registry; add dataclass migration; acknowledge API calls; add Risk section (6 risks); correct efforts | Claude Code |
| 2026-03-23 | R2 review: Codex 9.4/10 PASS, Gemini 9.4/10 PASS. Approved. | Claude Code |
