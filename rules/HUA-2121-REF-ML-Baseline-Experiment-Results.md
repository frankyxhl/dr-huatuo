# REF-2121: ML Baseline Experiment Results

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Active

---

## What Is It?

Experimental results from three approaches to distinguishing buggy vs fixed Python code using huatuo's static analysis metrics. All three produced negative results, establishing a clear boundary for what file-level static metrics can and cannot do.

---

## Experimental Setup

- **Dataset:** BugsInPy, 4 projects (thefuck, scrapy, keras, luigi)
- **Samples:** 176 paired files (buggy + fixed version of each), 352 total records
- **Features:** 25 numeric metrics from `dataset_annotator.py` (Tier 1)
- **Validation:** Leave-One-Project-Out (LOPO) 4-fold cross-validation
- **Date:** 2026-03-22

## Results

| Method | LOPO Accuracy/PCR | vs Random (50%) | Verdict |
|---|---|---|---|
| Linear scoring formula (HUA-2118) | 0.7% PCR | -49.3 pp | Worse than random |
| RandomForest (200 trees) | 50.7% ±1.9% | +0.7 pp | = Random |
| GradientBoosting (200 trees) | 51.2% ±1.5% | +1.2 pp | = Random |

### Per-project breakdown (RandomForest)

| Project | Pairs | Accuracy |
|---|---|---|
| thefuck | 36 | 50.0% |
| scrapy | 49 | 48.0% |
| keras | 56 | 51.8% |
| luigi | 35 | 52.9% |

### Feature importance (RandomForest, trained on all data)

| Rank | Feature | Importance |
|---|---|---|
| 1 | loc | 0.1043 |
| 2 | maintainability_index | 0.0833 |
| 3 | comment_density | 0.0831 |
| 4 | pylint_score | 0.0813 |
| 5 | avg_complexity | 0.0613 |
| 6 | halstead_volume | 0.0534 |
| 7 | halstead_effort | 0.0531 |
| 8 | cognitive_complexity | 0.0492 |
| 9 | halstead_difficulty | 0.0469 |
| 10 | N2 | 0.0453 |

No feature exceeds 0.11 importance — all are noise-level for this task.

## Analysis

### Why static metrics fail on BugsInPy

1. **Feature-task mismatch:** Our 25 metrics measure code style, complexity, security patterns, and maintainability. BugsInPy bugs are logic errors (wrong regex, missing boundary check, incorrect condition).

2. **Granularity mismatch:** Bug fixes typically change 1–3 lines. File-level metrics (aggregated over 50–500 LOC) are insensitive to such small changes.

3. **Phase 2 already hinted at this:** Cohen's d for individual metrics ranged 0.2–0.7 (small effects), but the sign consistency was low (56% at best for `loc`). Small effects + low consistency = no discriminative power when combined.

### What this does NOT mean

- Does NOT mean static metrics are useless — they are valuable for **project health dashboards** and **dataset curation** (filtering low-quality code).
- Does NOT mean the annotation pipeline is useless — the metrics provide a rich feature space for tasks where static properties matter (e.g., code quality scoring, technical debt estimation).
- DOES mean that **logic bug detection requires code semantic features**, not file-level static metrics.

## Implications for Phase 3

| Approach | Expected value | Rationale |
|---|---|---|
| Code diff features (AST diff between buggy/fixed) | High | Bug IS the diff — features that see the diff directly should have signal |
| Code embeddings (CodeBERT/UniXcoder) | Medium-High | Captures semantic patterns; but file-level embedding may still lose 1-line changes |
| LLM prompt with raw code (HUA-2119) | Medium | LLM can "see" the code structure; but depends on prompt quality |
| LLM prompt with metrics only | Low | Same information as RF/XGBoost — LLM won't find signal that isn't there |
| More static metrics | Low | The bottleneck is feature type, not feature count |

**Recommended Phase 3 direction:** Code diff features or LLM with raw code access (not metrics-only prompt).

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | Initial version — negative results from 3 approaches | Claude Code |
