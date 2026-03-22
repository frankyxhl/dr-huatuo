# PRP-2118: Scoring Formula Optimization

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Related:** HUA-2109-PRP (Annotator), HUA-2116-PRP (BugsInPy Validation), HUA-2119-PRP (AutoResearch Phase 3)
**Reviewed by:** —

---

## Background

Phase 2 validation (HUA-2116) on 176 BugsInPy paired samples across 4 projects showed:
- Aggregate `score` is insensitive to buggy/fixed differences (Cohen's d = -0.17, pair-correct rate ~50%)
- Individual metrics carry signal: `avg_complexity` (d≥0.2 in 4/4 projects), `cyclomatic_complexity` (4/4), `loc`/`cognitive_complexity`/`halstead_*` (3/4)
- The scoring formula weights were hand-tuned for project health dashboards, not ML dataset labeling

The formula has ~10 numeric parameters (5 weights + 5 caps). This is a standard hyperparameter optimization problem solvable with `scipy.optimize` in seconds — no LLM-based tool needed.

---

## What Is It?

A new script `scoring_optimizer.py` that uses BugsInPy paired data to find scoring formula weights that maximize the pair-correct rate (% of pairs where fixed file scores higher than buggy file). Pure numeric optimization via `scipy.optimize.differential_evolution`.

---

## Problem

### 1. Current weights are hand-tuned, not data-driven

Current formula: `ruff -2/max-30, complexity (cc-10)×5/max-20, bandit HIGH -15/max-30, bandit MEDIUM -5/max-15, mypy -1/max-10`. These weights reflect engineering judgment, not empirical optimization against labeled data.

### 2. Score is nearly a coin flip on buggy vs fixed

Phase 2 pair-correct rate for `score` is approximately 50%. Individual metrics (loc 56%, cognitive_complexity 33% of pairs show fixed > buggy) outperform the aggregate. Better weights can improve this.

### 3. Three scoring formulas exist but only two are in scope

| Module | Complexity weight | Cap | Notes |
|---|---|---|---|
| `code_analyzer.py` | ×5 | 20 | Dashboard use — **not optimized** (keep hand-tuned) |
| `code_reporter.py` | ×3 | 25 | Dashboard use — **not optimized** (keep hand-tuned) |
| `dataset_annotator.py` | ×5 | 20 | Research use — **optimization target** |

Only `dataset_annotator.py`'s standalone `_calculate_score()` is in scope. The dashboard formulas in `code_analyzer.py` and `code_reporter.py` are intentionally preserved (their divergence is documented in HUA-2104-SOP).

---

## Scope

**In scope (v1):**
- `scoring_optimizer.py`: optimize `dataset_annotator.py`'s scoring weights using `scipy.optimize`
- Objective: maximize pair-correct rate on BugsInPy paired data
- Held-out validation: optimize on 3 projects, validate on 1 held-out project
- Output: optimized weights + before/after comparison report
- If improvement ≥ 10 percentage points: file ADR + update `dataset_annotator.py`
- If marginal: document findings, keep current weights

**Out of scope (v1):**
- Dashboard scoring formulas (`code_analyzer.py`, `code_reporter.py`) — not touched
- LLM prompt optimization — see HUA-2119-PRP (AutoResearch, Phase 3)
- Training ML models (separate Phase 3)
- Adding new metrics to the scoring formula (only re-weighting existing ones)

---

## Proposed Solution

### Optimization approach

```python
from scipy.optimize import differential_evolution

def objective(params, pairs):
    """Negative pair-correct rate (minimize)."""
    ruff_w, ruff_cap, cc_thresh, cc_w, cc_cap, \
    bh_w, bh_cap, bm_w, bm_cap, mypy_w, mypy_cap = params

    correct = 0
    for buggy, fixed in pairs:
        buggy_score = calculate_score(buggy, params)
        fixed_score = calculate_score(fixed, params)
        if fixed_score > buggy_score:
            correct += 1
    return -correct / len(pairs)

bounds = [
    (0, 10),   # ruff_weight
    (10, 50),  # ruff_cap
    (5, 20),   # complexity_threshold
    (1, 15),   # complexity_weight
    (10, 40),  # complexity_cap
    (5, 30),   # bandit_high_weight
    (10, 50),  # bandit_high_cap
    (1, 15),   # bandit_medium_weight
    (5, 30),   # bandit_medium_cap
    (0.5, 5),  # mypy_weight
    (5, 20),   # mypy_cap
]

result = differential_evolution(objective, bounds, args=(train_pairs,),
                                seed=42, maxiter=1000, tol=1e-6)
```

### Why `differential_evolution`?

- Global optimizer — avoids local minima in a non-convex landscape (scoring formula has caps and thresholds)
- No gradient needed — works on the discrete pair-correct metric
- Deterministic with seed — reproducible results
- Fast — 176 pairs × ~10K evaluations ≈ seconds on a laptop

### Validation strategy: Leave-One-Project-Out Cross-Validation

Single held-out (35 pairs from luigi) is too small — the ≥10 pp gate would hinge on ~4 pairs. Instead, use **4-fold LOPO CV**: each fold holds out one project, optimizes on the other 3, and evaluates on the held-out project. Final reported PCR is the **mean across 4 folds**.

| Fold | Train projects | Train pairs | Held-out | Held-out pairs |
|---|---|---|---|---|
| 1 | scrapy, keras, luigi | 140 | thefuck | 36 |
| 2 | thefuck, keras, luigi | 127 | scrapy | 49 |
| 3 | thefuck, scrapy, luigi | 120 | keras | 56 |
| 4 | thefuck, scrapy, keras | 141 | luigi | 35 |

This gives 4 independent generalization estimates. If mean held-out PCR improvement ≥ 10 pp with std < 10 pp, the weights are considered robust.

### Module structure

```python
ScoringOptimizer
  __init__(train_pairs, test_pairs=None)
  optimize() -> OptimizationResult
  _load_pairs(project_dirs) -> list[tuple[dict, dict]]  # (buggy, fixed) annotated records
  _pair_correct_rate(params, pairs) -> float
  _calculate_score_with_params(metrics, params) -> float

@dataclass
class OptimizationResult:
    current_weights: dict
    current_train_pcr: float       # pair-correct rate on train
    current_test_pcr: float | None # pair-correct rate on held-out
    optimized_weights: dict
    optimized_train_pcr: float
    optimized_test_pcr: float | None
    improvement_train: float       # percentage points
    improvement_test: float | None
    scipy_result: Any              # raw scipy output
```

### CLI

```bash
# Optimize using extracted BugsInPy data
python scoring_optimizer.py --train thefuck scrapy keras --test luigi

# Optimize with all projects (no held-out)
python scoring_optimizer.py --train thefuck scrapy keras luigi

# Dry run: compute current pair-correct rates without optimizing
python scoring_optimizer.py --train thefuck scrapy keras --test luigi --baseline-only
```

### Output

```
Scoring Formula Optimization Report
====================================

Current weights:
  ruff: -2/violation, cap 30
  complexity: (cc-10)*5, cap 20
  bandit_high: -15, cap 30
  bandit_medium: -5, cap 15
  mypy: -1, cap 10

Current pair-correct rate:
  Train (141 pairs): 52.5%
  Held-out (35 pairs): 48.6%

Optimized weights:
  ruff: -1.3/violation, cap 22
  complexity: (cc-8)*7.2, cap 18
  ...

Optimized pair-correct rate:
  Train (141 pairs): 68.1%
  Held-out (35 pairs): 62.9%

Improvement: +15.6 pp (train), +14.3 pp (held-out)
Recommendation: UPDATE (>= 10 pp improvement on held-out)
```

### Integration path

If mean LOPO held-out PCR improvement ≥ 10 pp (std < 10 pp):
1. File ADR (COR-1100) documenting the rationale and before/after data
2. Update `dataset_annotator.py:_calculate_score()` with new weights
3. **Retire parity contract:** `dataset_annotator.py` currently documents its scoring as "same as CodeAnalyzer._calculate_score" (line 52 docstring) and `tests/test_dataset_annotator.py:TestScoringParity` enforces identical output. After optimization:
   - Update docstring to "research-optimized weights (see ADR-XXXX)"
   - Replace `TestScoringParity` with `TestOptimizedScoring` that verifies the new weights
   - Update CLAUDE.md scoring documentation to note the divergence
4. `code_analyzer.py` and `code_reporter.py` **unchanged** — dashboard weights are a separate concern
5. Re-run Phase 2 analysis to update validation reports

### Dependencies

- `scipy` — install: `pip install scipy` in project venv (`.venv/bin/pip install scipy`); version pinned in implementation (e.g., `scipy>=1.11`); MIT license
- BugsInPy annotated data from Phase 2 (176 pairs, already extracted across 4 projects)

### Impact

- **New file:** `scoring_optimizer.py`
- **New tests:** `tests/test_scoring_optimizer.py` (pair-correct rate computation, parameter bounds, optimization convergence, held-out validation)
- **New dependency:** `scipy` (add to venv)
- **Makefile:** add `scoring_optimizer.py` to `lint` and `fmt`
- **Potential code change:** `dataset_annotator.py:_calculate_score()` weights (only if improvement ≥ 10 pp + ADR approval)
- **`code_analyzer.py` / `code_reporter.py`:** no changes

---

## Open Questions

_All open questions resolved before review._

1. **Why `differential_evolution` and not grid search?** 11 parameters with continuous ranges → grid search is exponential. DE is a global optimizer that handles continuous parameters efficiently. With `maxiter=1000` and 176 pairs, it completes in seconds.

2. **Is 176 pairs enough?** For 11 parameters, the ratio is ~16 samples per parameter. This is tight but acceptable for DE with bounds constraints. The held-out split (35 pairs) detects gross overfitting. If train PCR >> test PCR (gap > 15 pp), we report "overfit" and do not update weights.

3. **Why hold out luigi specifically?** It has the weakest Phase 2 signal (top metric d=0.37, vs keras d=0.72). If optimized weights work on the hardest case, they generalize. Alternative: cross-validation across all 4 projects (4-fold, each project as held-out once).

4. **What if no improvement is found?** Document the finding — it means the scoring formula's functional form (linear deductions with caps) is inherently limited. Phase 3 should then focus on ML models that learn non-linear combinations, not on re-weighting the same formula.

5. **Why not optimize `code_analyzer.py` too?** Its formula serves project health dashboards where the weights reflect engineering priorities (e.g., security findings weighted heavily). Research-optimized weights may not match dashboard user expectations. Keeping them separate avoids conflating two use cases.

6. **Actual baseline pair-correct rate?** Must be computed empirically from Phase 2 data before optimization begins (not estimated from Cohen's d). The script computes this as step 1 (`--baseline-only` flag).

---

## Review

- [x] Reviewer 1 (Codex): 9 / 10 — APPROVED (v3, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9 / 10 — APPROVED (v2, 2026-03-22)
- [x] Approved on: 2026-03-22

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v3: LOPO CV replacing single held-out; parity contract retirement plan; scipy install path specified | Claude Code |
| 2026-03-22 | v2: Complete rewrite — replaced AutoResearch with scipy.optimize differential_evolution; addressed Codex (7/10) and Gemini (4/10 REJECTED) feedback; split AutoResearch to HUA-2119; added code_reporter.py divergence note; added held-out validation; added empirical baseline requirement | Claude Code |
| 2026-03-22 | v1: Initial version (AutoResearch-based, rejected) | Claude Code |
