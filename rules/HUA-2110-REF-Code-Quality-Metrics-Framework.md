# REF-2110: Code Quality Metrics Framework

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Active

---

## What Is It?

Initial draft of the Python code quality metrics framework for the dataset annotation pipeline (HUA-2109-PRP). Catalogues all candidate JSONL fields by source: existing tools, unused radon capabilities, AST structural metrics, readability metrics, Python-specific antipatterns, and duplication detection. Includes a Tier 1/2/3 prioritisation and a list of open questions sent for external review.

**Note:** Parts of this document have been revised by findings in HUA-2111 (external research responses). Read both documents together.

---

## Content

### Current Fields — 5 Existing Tools

| Field | Source | Meaning |
|---|---|---|
| `ruff_violations` | ruff | PEP8 / style violation count |
| `max_complexity` | radon cc | Highest cyclomatic complexity in file |
| `avg_complexity` | radon cc | Average cyclomatic complexity |
| `func_count` | radon cc | Number of functions analysed |
| `bandit_high` | bandit | High-severity security issues |
| `bandit_medium` | bandit | Medium-severity security issues |
| `mypy_errors` | mypy | Type errors |
| `pylint_score` | pylint | pylint quality score (0–10) |
| `score` | huatuo (weighted formula) | Composite quality score (0–100) |
| `grade` | huatuo | Letter grade A / B / C / D / F |

**Limitation:** All fields are single-file or single-function granularity. No structural or relational analysis.

### Unused radon Capabilities

#### Halstead Metrics (`radon hal file.py`)

| Field | Meaning | Status |
|---|---|---|
| `halstead_n1/n2/N1/N2` | Raw operator / operand counts | Keep — reproducible primary inputs |
| `halstead_volume` | Information content of code | Keep — derived, useful |
| `halstead_difficulty` | Estimated reading difficulty | Keep — derived, useful |
| `halstead_effort` | Estimated mental effort | Keep — derived, useful |
| `halstead_bugs` | Estimated bug count (volume / 3000) | ⚠️ Disputed — demoted to Tier 3 (see HUA-2111 Q1) |

#### Maintainability Index (`radon mi file.py`)

| Field | Meaning | Range |
|---|---|---|
| `maintainability_index` | Combined cyclomatic complexity + Halstead volume + LOC | 0–100, higher = more maintainable |

### AST Structural Metrics (Python `ast` module, no additional tools)

#### Depth and Hierarchy

| Field | Meaning | Threshold |
|---|---|---|
| `max_nesting_depth` | Maximum if / for / while nesting depth | > 3 degrades readability; > 5 severe |
| `inheritance_depth` | Longest inheritance chain (DIT, CK metric) | > 3 = over-engineered |
| `noc` | Number of direct subclasses (NOC, CK metric) | High = large blast radius on base-class changes |

#### Function and Class Granularity

| Field | Meaning | Threshold |
|---|---|---|
| `class_count` | Number of class definitions in file | — |
| `avg_function_lines` | Average lines per function | > 20 getting long |
| `max_function_lines` | Longest function in lines | > 50 = should be split |
| `max_params` | Maximum parameter count per function | > 5 = too many |
| `wmc` | Weighted Methods per Class — sum of method complexities (CK metric) | High = harder to test |

#### Module Dependencies

| Field | Meaning |
|---|---|
| `import_count` | Total import statements |
| `stdlib_imports` | Standard library imports |
| `third_party_imports` | Third-party package imports |
| `local_imports` | Relative imports (`.foo`) |
| `fan_out` | Number of distinct modules depended on |

#### Cohesion

| Field | Meaning |
|---|---|
| `lcom` | Lack of Cohesion in Methods (CK metric) — see HUA-2111 Q2 for version choice |
| `rfc` | Response For a Class (CK metric) |

### Readability and Naming Metrics

| Field | Meaning | Implementation |
|---|---|---|
| `docstring_coverage` | Fraction of functions with docstrings (0.0–1.0) | AST: check first node of each FunctionDef |
| `comment_density` | Comment lines / total lines | Text scan |
| `avg_identifier_length` | Average character length of identifiers | AST: walk Name nodes |
| `magic_number_count` | Bare numeric literals excluding 0 and 1 | AST: Constant nodes |

### Python-Specific Antipatterns

| Field | Meaning | Example |
|---|---|---|
| `mutable_default_args` | Functions with mutable default arguments | `def f(x=[])` — classic Python trap |
| `bare_except_count` | Bare `except:` clauses | Swallows all exceptions silently |
| `global_mutations` | Global variable mutations inside functions | Hidden side effects |
| `lambda_complexity` | Lambdas with multi-expression logic | Difficult to debug |
| `assert_in_production` | `assert` statements outside test files | Disabled by `-O` flag at runtime |

### Duplication

| Field | Meaning | Tool |
|---|---|---|
| `duplicate_blocks` | Number of duplicate code blocks | jscpd (npm) or pylint R0801 |
| `duplicate_percentage` | Percentage of duplicated lines (0–100) | jscpd |

### Tier Classification (Initial Draft)

**Tier 1 — required in v1:**
Current 10 fields + `maintainability_index` + `halstead_volume` / `halstead_difficulty` + `max_nesting_depth` + `docstring_coverage` + `max_params` + `mutable_default_args` + `bare_except_count` + `import_count` / `fan_out`

**Tier 2 — optional (`--full` mode):**
`inheritance_depth` / `noc` + `wmc` / `lcom` / `rfc` + `avg_function_lines` + `duplicate_percentage`

**Tier 3 — experimental (validate effectiveness before use):**
`halstead_bugs` + `global_mutations` + `comment_density` + `cbo`

### JSONL Schema Draft (Tier 1, initial version)

```json
{
  "path": "path/to/file.py",
  "source": "BugsInPy",
  "license": "MIT",
  "label": "buggy",
  "score": 34.0,
  "grade": "F (Fail)",
  "ruff_violations": 8,
  "max_complexity": 22,
  "avg_complexity": 11.3,
  "func_count": 6,
  "bandit_high": 1,
  "bandit_medium": 2,
  "mypy_errors": 5,
  "pylint_score": 4.2,
  "maintainability_index": 18.4,
  "halstead_volume": 842.0,
  "halstead_difficulty": 31.2,
  "max_nesting_depth": 5,
  "docstring_coverage": 0.33,
  "max_params": 7,
  "mutable_default_args": 1,
  "bare_except_count": 2,
  "import_count": 9,
  "fan_out": 7,
  "line_count": 187,
  "error": null
}
```

### Open Questions (answered in HUA-2111)

1. Is `halstead_bugs` still predictive on modern Python codebases?
2. Which LCOM version (1–5) is most appropriate for Python AST analysis?
3. How to handle correlated features: PCA vs. feature selection?
4. Cognitive Complexity vs. Cyclomatic Complexity — which better captures human readability?
5. What are the limitations of BugsInPy buggy/fixed diff as a validation method?
6. AST structural metrics vs. token-level metrics — which provides more signal for LLM fine-tuning?
7. How to compute CBO meaningfully in dynamically-typed Python?

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | Initial version, migrated and translated from docs/code-quality-metrics-framework.md | Claude Code |
