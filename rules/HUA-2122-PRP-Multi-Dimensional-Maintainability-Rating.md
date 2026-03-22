# PRP-2122: Multi-Dimensional Code Quality Profile

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Related:** HUA-2109-PRP (Annotator), HUA-2121-REF (ML Baseline Results)
**Reviewed by:** —

---

## Background

Phase 2 experiments (HUA-2121) confirmed huatuo's static metrics measure **maintainability**, not bugs. The current single score (0–100) conflates security, type safety, style, and maintainability into one opaque number with hand-tuned weights.

This PRP replaces the single score with a **multi-dimensional profile** of 5 independent dimensions. Each dimension has its own rating. There is no aggregate score — the dimensions are intentionally kept separate because they measure different concerns.

---

## What Is It?

A `quality_profile.py` module that evaluates Python files across 5 independent dimensions, each with a separate rating. No aggregate score. Every threshold is tagged with its evidence level.

---

## Problem

### 1. Single score conflates unrelated concerns

Security findings (bandit), type errors (mypy), code style (ruff), and maintainability (MI/complexity) are fundamentally different. A file with `bandit_high=1` and a file with `cyclomatic_complexity=25` both score ~70, but need completely different actions.

### 2. Double-counting in any aggregate

`maintainability_index` already incorporates cyclomatic complexity, LOC, Halstead volume, and comment ratio (Oman & Hagemeister 1992). Any rubric that scores MI AND also scores CC, LOC, and comments separately double-counts these factors. The only way to avoid this is to not aggregate.

### 3. Thresholds need honest evidence tagging

Not all thresholds have peer-reviewed sources. Claiming "McCabe 1976" for a 4-band rubric that McCabe never published is misleading. This PRP uses a 3-tier evidence system: Published Research, Tool Documentation, and Industry Convention.

---

## Scope

**In scope:**
- 5 independent dimensions, each with its own rating (no aggregate)
- 3-tier evidence tagging for every threshold
- `quality_profile.py` standalone module
- Integration into `dataset_annotator.py` output

**Out of scope:**
- Replacing existing `score/grade` (kept for backward compatibility)
- Per-function breakdown
- Aggregate/composite score (intentionally avoided)

---

## Proposed Solution

### Evidence tiers

Every threshold in this PRP is tagged with one of:

| Tag | Meaning | Example |
|---|---|---|
| **[Research]** | Published in peer-reviewed paper or formal technical report with specific numeric threshold | McCabe 1976: CC > 10 = "more complex" |
| **[Tool]** | Documented in the tool's official docs as a default, scale, or recommendation | pylint: 0–10 scale; ruff: zero-violation target |
| **[Convention]** | Widely used in industry but no single authoritative source; we choose this threshold | loc ≤ 200 for "concise" (inspired by Martin but not a formal rule) |

### Dimension 1: Maintainability

**Primary metric: `maintainability_index`** (MI, computed by radon)

MI is a composite metric incorporating Halstead volume, cyclomatic complexity, lines of code, and comment percentage (Oman & Hagemeister 1992). It is the most studied single maintainability metric and avoids double-counting.

| Rating | MI range | Label | Evidence |
|---|---|---|---|
| A | ≥40 | Highly maintainable | **[Convention]** Upper half of radon rank "A" (MI > 19); 40 chosen as a split point for finer granularity |
| B | ≥20 and <40 | Moderately maintainable | **[Tool]** radon rank "A" lower boundary = 20; matches Microsoft VS "green" threshold |
| C | ≥10 and <20 | Difficult to maintain | **[Tool]** radon rank "B" (MI 10–19, "medium maintainability") |
| D | <10 | Unmaintainable | **[Tool]** radon rank "C" (MI < 10, "extremely low maintainability") |

**Threshold note:** radon documents 3 MI ranks: A (> 19), B (10–19), C (< 10). Microsoft Visual Studio uses the same 20/10 boundaries (green/yellow/red). We split radon's "A" range at 40 for finer granularity — this split is **[Convention]**, not literature-backed. The 20 and 10 boundaries are **[Tool]**.

**Why MI alone?** Because individually scoring CC, LOC, Halstead, and comments that MI already contains would double-count. MI is the authoritative composite. The individual metric values are still available in the raw output for anyone who wants to drill deeper.

### Dimension 2: Complexity (what MI doesn't fully capture)

MI uses cyclomatic complexity but does NOT capture:
- **Cognitive complexity** — how hard the code is for a human to understand (SonarSource 2016)
- **Nesting depth** — deeply nested code is harder to follow even at moderate CC

| Metric | A | B | C | D | Evidence |
|---|---|---|---|---|---|
| `cognitive_complexity` | ≤5 | >5 and ≤15 | >15 and ≤25 | >25 | **[Research]** SonarSource 2016 whitepaper: default rule threshold = 15; Campbell recommends refactoring above 15 |
| `max_nesting_depth` | ≤2 | 3 | 4–5 | ≥6 | **[Convention]** Linux kernel coding style recommends ≤3 indentation levels; Linus Torvalds' widely-cited guideline |

**Dimension rating = worst of the two metrics.** If cognitive is A but nesting is C, the dimension is C. The `limiting_metric` field shows which one.

### Dimension 3: Code Style

Adherence to Python conventions and best practices.

| Metric | A | B | C | D | Evidence |
|---|---|---|---|---|---|
| `ruff_violations` | 0 | 1–3 | 4–10 | >10 | A=0 is **[Tool]** (ruff target); B/C/D bands are **[Convention]** |
| `pylint_score` | ≥9.0 | ≥7.0 and <9.0 | ≥5.0 and <7.0 | <5.0 | **[Tool]** pylint 0–10 scale; A/B/C/D cutoffs are **[Convention]** (common CI gates, not official pylint recommendation) |

**Dimension rating = worst of the two metrics.**

### Dimension 4: Documentation

Can a new developer understand this code without external context?

| Metric | A | B | C | D | Evidence |
|---|---|---|---|---|---|
| `docstring_density` | ≥0.80 | ≥0.50 and <0.80 | ≥0.20 and <0.50 | <0.20 | **[Convention]** PEP 257 recommends docstrings for "all public modules, functions, classes, and methods" but does not define a percentage; 80% is our chosen target for "well-documented" |
| `comment_density` | ≥0.10 and ≤0.30 | (≥0.05 and <0.10) or (>0.30 and ≤0.40) | ≥0.01 and <0.05 | <0.01 or >0.40 | **[Convention]** McConnell "Code Complete" 2004: suggests ~10–30% comment density is healthy, but this is a guideline not a formal threshold |

**Dimension rating = worst of the two metrics.**

**Edge cases:**
- `function_count == 0`: `docstring_density` is undefined → excluded; rating based on `comment_density` alone. Note: current `docstring_density` only measures function docstrings, not module-level or class-level docstrings (HUA-2109 AST definition limitation).
- `loc == 0`: `comment_density` is undefined → excluded; dimension = N/A
- Any metric is `null`: that metric is excluded; if all metrics in a dimension are null, dimension = N/A

**Overlap acknowledgment:** MI (Dimension 1) incorporates comment % as one of its 4 inputs. `comment_density` is also rated here. This is a known partial overlap. The two dimensions serve different purposes: MI uses comment % as part of an overall maintainability composite; Documentation evaluates it directly as a readability signal.

### Dimension 5: Security (pass/fail gate, NOT a score)

Security is not a "maintainability" concern — it's a **blocker**. A file with `bandit_high ≥ 1` should not get a partial score; it should be flagged.

| Status | Criteria | Evidence |
|---|---|---|
| **PASS** | `bandit_high` = 0 AND `bandit_medium` ≤ 2 | **[Tool]** Bandit severity levels; **[Convention]** medium ≤ 2 threshold |
| **WARN** | `bandit_high` = 0 AND `bandit_medium` > 2 | **[Convention]** No standard source; chosen as "multiple medium findings warrant attention" |
| **FAIL** | `bandit_high` ≥ 1 | **[Tool]** Bandit HIGH severity; **[Convention]** zero-tolerance for HIGH findings (inspired by OWASP, not a direct OWASP rule) |

Security is reported separately, not mixed into any score. A file can have Maintainability: A and Security: FAIL.

### Type Safety (informational, NOT rated)

`mypy_errors` is **not rated** because it is highly environment-sensitive (HUA-2109-PRP v10: missing dependencies/stubs produce false positives in single-file analysis). Instead, it is reported as-is:

```
Type Safety: 2 mypy errors (⚠️ environment-sensitive — see data_warnings)
```

If `data_warnings` contains `"suspect:mypy_env"`, the output explicitly notes: "mypy results may reflect missing dependencies, not actual type issues."

### Output schema

```json
{
  "qp_maintainability": "A",
  "qp_maintainability_mi": 52.3,
  "qp_complexity": "C",
  "qp_complexity_limiting": "cognitive_complexity",
  "qp_complexity_detail": {"cognitive_complexity": "C", "max_nesting_depth": "A"},
  "qp_code_style": "B",
  "qp_code_style_limiting": "pylint_score",
  "qp_code_style_detail": {"ruff_violations": "A", "pylint_score": "B"},
  "qp_documentation": "D",
  "qp_documentation_limiting": "docstring_density",
  "qp_documentation_detail": {"docstring_density": "D", "comment_density": "B"},
  "qp_security": "PASS",
  "qp_security_detail": {"bandit_high": 0, "bandit_medium": 1},
  "qp_mypy_errors": 2,
  "qp_mypy_env_sensitive": false,
  "qp_summary": "M:A Cx:C St:B Doc:D Sec:PASS"
}
```

- `qp_` prefix (quality profile) to avoid collision
- Each dimension has a top-level rating + `_detail` showing per-metric ratings
- `_limiting` shows which metric caused a non-A rating
- `qp_summary` is a compact one-line string for quick scanning
- **No aggregate score** — dimensions are independent
- **Null handling:** if all metrics in a dimension are null, the dimension rating is `null` in JSON and "N/A" in summary. Null dimensions are excluded from the summary string

### Terminal output

```
example_code.py — Quality Profile
  Maintainability: B  (MI=52.3)
  Complexity:      C  (cognitive_complexity=18 > 15)
  Code Style:      A  (ruff=0, pylint=9.2)
  Documentation:   D  (docstring_density=0.10 < 0.20)
  Security:        PASS (0 high, 1 medium)
  Type Safety:     2 mypy errors

  Action items:
    1. Documentation: add docstrings (docstring_density=0.10, need ≥0.20 for C)
    2. Complexity: reduce cognitive complexity (18 → ≤15 for B)
```

The "Action items" section lists dimensions rated C or D with the specific metric and how much improvement is needed to reach the next tier.

### Module structure

```python
# quality_profile.py

@dataclass
class DimensionResult:
    name: str              # "maintainability", "complexity", etc.
    rating: str | None     # "A"/"B"/"C"/"D" or "PASS"/"WARN"/"FAIL" or None (N/A)
    limiting_metric: str | None
    detail: dict[str, str | int | float]

@dataclass
class QualityProfile:
    maintainability: DimensionResult
    complexity: DimensionResult
    code_style: DimensionResult
    documentation: DimensionResult
    security: DimensionResult
    mypy_errors: int | None
    mypy_env_sensitive: bool
    summary: str

def profile_file(metrics: dict) -> QualityProfile:
    """Generate a quality profile from annotated metrics."""

# Per-dimension rating functions
def _rate_maintainability(mi: float | None) -> DimensionResult:
def _rate_complexity(cognitive: int | None, nesting: int | None) -> DimensionResult:
def _rate_code_style(ruff: int | None, pylint: float | None) -> DimensionResult:
def _rate_documentation(docstring_d: float | None, comment_d: float | None,
                         function_count: int | None, loc: int | None) -> DimensionResult:
def _rate_security(bandit_high: int | None, bandit_medium: int | None) -> DimensionResult:
```

### Dependencies

None. Pure Python, uses only metric values from `dataset_annotator.py`.

### Impact

- **New file:** `quality_profile.py`
- **New tests:** `tests/test_quality_profile.py` (each dimension's A/B/C/D boundaries, edge cases for 0/null, security PASS/WARN/FAIL, limiting_metric correctness, summary string format)
- **Modified:** `dataset_annotator.py` — call `profile_file()` and add `qp_*` fields
- **Makefile:** add `quality_profile.py` to `lint` and `fmt`

---

## Open Questions

_All open questions resolved before review._

1. **Why no aggregate score?** Any aggregate recreates the exact problem we're solving. If you weight dimensions, you get an opaque composite. If you don't weight, security and documentation are "equal" — which is nonsensical. Independent dimensions are the honest representation.

2. **Why is MI the sole maintainability metric (not CC, LOC, etc.)?** MI already incorporates CC, LOC, Halstead volume, and comment ratio. Scoring MI AND its components separately double-counts. MI is peer-reviewed (Oman & Hagemeister 1992, Coleman et al. 1994) and the most widely adopted maintainability index. Individual values remain in the raw output.

3. **Why isn't mypy rated?** HUA-2109-PRP v10 documented that single-file mypy analysis produces false positives from missing dependencies/stubs. Rating an environment-sensitive metric as if it were a code quality signal would be misleading. It's reported as-is with an environment caveat.

4. **Why is security pass/fail instead of scored?** A file with `bandit_high=1` and excellent code style is not "85% secure." It has a security finding that needs to be addressed regardless of other qualities. Pass/fail is the honest representation. Partial credit for security is misleading.

5. **Why 3 evidence tiers?** Not all thresholds are created equal. Claiming "McCabe 1976" for a threshold McCabe didn't publish is academic dishonesty. The 3-tier system ([Research] / [Tool] / [Convention]) lets users judge the authority behind each threshold. Convention-based thresholds can be debated and customized; research-based ones have stronger standing.

6. **What about `loc`, `function_count`, `class_count`, `avg_complexity`, Halstead metrics?** They remain in the raw metric output. They are not rated in the profile because: (a) MI already covers loc + Halstead + CC + comments; (b) function/class count thresholds have no authoritative source (Martin's "Clean Code" offers guidelines, not numeric thresholds); (c) avg_complexity is correlated with cyclomatic_complexity. Users who want to set project-specific thresholds on these can do so downstream.

---

## Review

- [x] Reviewer 1 (Codex): 9 / 10 — APPROVED (v5, 2026-03-22)
- [x] Reviewer 2 (Gemini): 8 / 10 → APPROVED after example fix (v5, 2026-03-22)
- [x] Approved on: 2026-03-22

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v5: Fixed MI thresholds to radon documented ranks (20/10 [Tool], 40 split [Convention]); fixed evidence tags on Code Style and Security; added null/N/A encoding; fixed comment_density micro-gap (<0.01); added qp_code_style_limiting; acknowledged comment_density/MI overlap; noted docstring_density limitation | Claude Code |
| 2026-03-22 | v4: Complete redesign per Codex rejection (4/10) — removed aggregate score; MI as sole maintainability metric (avoids double-counting); security as pass/fail gate; mypy as informational only; 3-tier evidence tagging; honest citations; 5 independent dimensions | Claude Code |
| 2026-03-22 | v3: Fixed float gaps, filled comment_density range | Claude Code |
| 2026-03-22 | v2: Per-metric 0–3 rubric (rejected: double-counting, citation issues) | Claude Code |
| 2026-03-22 | v1: 6 dimensions Good/Moderate/Poor (rejected: too vague) | Claude Code |
