# REF-2111: External Research: Code Quality Metrics Responses

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Active

---

## What Is It?

Responses from an external research-grade AI (with literature citations) to the 7 open questions listed in HUA-2110. Covers Halstead validity, LCOM version selection, correlated feature handling, Cognitive vs. Cyclomatic Complexity, BugsInPy validation limitations, LLM fine-tuning signal selection, and CBO approximation in Python. Findings directly inform the revised schema in HUA-2109-PRP.

**Related documents:** HUA-2110 (initial metrics draft), HUA-2109 (dataset annotator proposal)

---

## Content

### Overall Recommendation: Three-Layer Schema

The external research recommends organising fields into three layers:

1. **Reproducible raw fields:** LOC, `n1/n2/N1/N2`, cyclomatic, essential complexity, max nesting depth, comment density, import fan-out
2. **Approximate structural fields:** `lcom4_approx`, `cbo_approx_static`, `cognitive_complexity` — name and version must be explicit
3. **Legacy / derived fields:** `halstead_volume`, `effort`, `bugs`, `time` — do not treat as ground-truth estimates

Core conclusion: **Do not use `halstead_bugs = volume/3000` as a primary field. Prioritise raw Halstead counts, McCabe/Cognitive complexity, nesting depth, comment density, module/symbol fan-out, and cohesion/coupling fields with explicit approximation labels.**

---

### Q1 — Is `halstead_bugs` still predictive on modern Python?

**Verdict: Weak signal at best; demote to legacy field.**

- ACM 2022 survey: Halstead "Software Science" predictions have not held up at scale; cross-project generalisation is poor
- 2023 PeerJ study: decomposed Halstead base counts outperform the derived composite metrics
- 2024 explainable defect-prediction study: retained `loc`, `v(g)`, `ev(g)`, `l`, `e` — not `b`
- No post-2015 paper found that validates `volume/3000` on modern Python with robust positive results

**Schema decisions:**
- Keep `n1`, `n2`, `N1`, `N2` (raw counts — reproducible)
- Keep `halstead_volume`, `halstead_difficulty`, `halstead_effort` (useful derived fields)
- Demote `halstead_bugs` to Tier 3 / legacy; do not label it "estimated bug count"

---

### Q2 — Which LCOM version suits Python AST analysis?

**Verdict: LCOM4 as primary; LCOM5 as secondary.**

- PyPI package `lcom` implements LCOM4: methods are connected if they share an instance attribute or call each other; `__init__` is excluded by default — fits Python's `self.x` style naturally
- LCOM5 is a continuous, normalisable ratio — friendlier to ML features
- Warning: a 2020 study found systematic problems in LCOM1–5; none perfectly captures cohesion as claimed

**Schema decisions:**
- Field names: `lcom4_approx`, `lcom5_hs`
- Record `lcom_impl_version` alongside
- Document constraint: single-file only, no MRO resolution, no dynamic attribute resolution

**LCOM4 algorithm (pure AST):**
1. Find each `ClassDef`; collect non-`__init__` instance methods
2. Per method: extract accessed `self.attr` and called `self.method()`
3. Connect two methods if they share an attribute or one calls the other
4. `LCOM4 = number of connected components in the method graph`

---

### Q3 — Correlated features: PCA vs. feature selection?

**Verdict: Prefer lightweight feature selection; avoid PCA unless interpretability is irrelevant.**

- 2016 study (101 defect datasets): 10–67% of metrics are redundant; leaving them in biases conclusions
- 2019 study: correlation-based and consistency-based feature selection outperforms PCA for supervised defect prediction
- 2024 study: association / coherence-based methods perform best; reducing features avoids multicollinearity and curse of dimensionality

**Recommended pipeline:**
1. Remove strongly derived duplicates by semantics (keep raw counts; drop high-correlation derivatives)
2. Compute Spearman clustering or VIF on the training set; keep the most interpretable field per cluster
3. Train both linear and tree-based models
4. Use PCA only if interpretability is not required

**Note:** For a code quality regression model, interpretability matters — "why did this file score low?" is a key use case. PCA components cannot answer that.

---

### Q4 — Cognitive Complexity vs. Cyclomatic Complexity

**Verdict: Keep both; they measure different things.**

| | Cyclomatic Complexity | Cognitive Complexity |
|---|---|---|
| Measures | Number of test paths | Mental effort to read the code |
| Strength | Test coverage planning | Human readability |
| Weakness | Does not reflect nesting penalty | Newer, less established |

- 2020 validation study: Cognitive Complexity is the first readability metric to receive systematic empirical support
- 2023 studies: Cognitive slightly outperforms Cyclomatic for perceived understandability, but margin is small and debate is ongoing

**New fields to add (both Tier 1):**
- `cognitive_complexity` — install `complexipy` (latest: 5.2.0, 2026-01-28) or `cognitive-complexity`
- `essential_complexity` — already in radon: `radon cc file.py -e`

---

### Q5 — Limitations of BugsInPy buggy/fixed diff as validation

**Verdict: It is a patch sensitivity test, not a prediction test.**

BugsInPy contains 493 real bugs from 17 Python projects — suitable for exploration but not for proving stable predictive validity.

**Limitations of paired buggy/fixed diff:**
1. Measures "does the metric change after a fix?" — not "can the metric predict bugs before they happen?"
2. File-level granularity is too coarse; bugs typically live in a single method or a few lines
3. No natural negative samples — no control group of files that were changed but did not introduce bugs
4. Within-project correlation violates iid assumption; significance is inflated
5. Fix commits often include refactoring alongside the bug fix, confounding the metric change

**More rigorous approach:**
- **Primary validation:** temporal within-project prediction — train on commits up to time T, predict defects after T; use SZZ algorithm to label bug-inducing changes
- **Secondary validation:** method-level paired diff with matched controls (same project, same time window, modified but not bug-related)
- **Statistics:** Wilcoxon / permutation test + Cliff's delta or rank-biserial effect size; bootstrap across projects

---

### Q6 — AST metrics vs. token metrics for LLM fine-tuning

**Verdict: Structural metrics first; selective token metrics second; avoid surface formatting stats.**

- Code models already handle syntax well; they struggle more with semantic structure (CFG, CDG, DDG)
- 2024 fusion study: AST semantic features + traditional metrics jointly outperform either alone
- 2024 ACL paper: `comment_density` in pre-training data significantly affects downstream task performance
- 2025 cross-language study (4 languages, 10 LLMs): removing formatting elements reduced input tokens by 24.5% with negligible performance change

**Prioritise (Tier 1):**
`max_nesting_depth`, `cognitive_complexity`, `cyclomatic_complexity`, `essential_complexity`, `function_count`, `class_count`, `fanout_modules`, `fanout_symbols`, `lcom4_approx`

**Selective token-level additions:**
`comment_density`, `docstring_density`, `avg_identifier_length`

**Not worth adding:**
Whitespace style, line-ending formats, and other pure surface formatting fields.

---

### Q7 — Computing CBO in dynamically-typed Python

**Verdict: Replace single `cbo` field with a set of honest approximation fields.**

- PyCG paper: precise Python call graphs require handling higher-order functions + metaprogramming; static-only analysis must accept incompleteness
- `pyan` documentation acknowledges ignoring runtime-order-dependent `self.f` bindings for simplicity
- 2025 study: static tools (PyCG) still outperform LLMs for call-graph completeness
- 2024 dynamic-language bug prediction: combining static + dynamic invocation metrics improved performance 2–10%

**Replace `cbo` with:**

```json
"fanout_modules": 4,
"fanout_imported_symbols": 12,
"resolved_external_calls": 8,
"unresolved_dynamic_calls": 3,
"cbo_approx_static": 4,
"cbo_resolution_rate": 0.73
```

`cbo_resolution_rate = resolved / (resolved + unresolved)` — tells the model how reliable the approximation is.

---

### Revised Tier Classification (post-research)

**Tier 1 — required in v1:**
`loc`, `n1`, `n2`, `N1`, `N2`, `halstead_volume`, `halstead_difficulty`, `halstead_effort`,
`cyclomatic_complexity`, `essential_complexity`, `cognitive_complexity`,
`max_nesting_depth`, `function_count`, `class_count`,
`fanout_modules`, `fanout_symbols`, `comment_density`, `docstring_density`,
existing 10 huatuo fields

**Tier 2 — conditional (`--full` mode):**
`lcom4_approx`, `lcom5_hs`, `cbo_approx_static`,
`resolved_external_calls`, `unresolved_dynamic_calls`, `cbo_resolution_rate`

**Tier 3 — legacy / experimental:**
`halstead_bugs`, `halstead_time`, other high-correlation derived fields

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | Initial version, translated and structured from external AI consultation | Claude Code |
