# PLN-2131: Product Roadmap

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Active

---

## What Is It?

Product roadmap for dr-huatuo, organized into milestones. Each milestone groups related work with a clear deliverable. Consult this document at session start to determine what to work on next.

---

## Goals

- Ship a reliable, usable Python code quality tool (`ht check`, `ht report`)
- Eliminate code duplication between the two CodeAnalyzer classes
- Extend to multi-language analysis (TypeScript first)

---

## Milestones

| # | Milestone | Deliverable | Status | Ref |
|---|-----------|-------------|--------|-----|
| 1 | **Foundation** | Single-file analyzer, project reporter, tests, CI/CD, PyPI | Done | v0.4.0 |
| 2 | **Quality Profile & CLI** | 5-dimension quality profile, `ht` CLI, quality gate, HTML drilldown | Done | HUA-2122, HUA-2124, HUA-2125, HUA-2126 |
| 3 | **Scoring Consistency** | Unified scoring formula, venv tool detection fix, missing-tool warnings | Done | HUA-2130-ADR, v0.4.0 |
| 4 | **Analyzer Unification** | Extract shared `PythonAnalyzer`, eliminate CodeAnalyzer duplication | Done | HUA-2129 Phase 1–4 |
| 5 | **Multi-Language** | TypeScriptAnalyzer, mixed-project support | In Progress | HUA-2129 Phase 5–6 |
| 7 | **GitHub Action** | Composite action for CI integration (`uses: frankyxhl/dr-huatuo@v1`) | Planned | PRP TBD |
| 6 | **Research Pipeline** | Dataset annotation, deduplication, BugsInPy validation, scoring optimizer | Done | HUA-2109–HUA-2121 |

---

## Milestone 4: Analyzer Unification (Next)

Per HUA-2129-PRP (approved). This is the top priority — it solves the code duplication problem and unblocks multi-language support.

| Phase | What | Effort | CHG |
|---|---|---|---|
| 1 | `LanguageAnalyzer` protocol + registry + auto-detection | Small | TBD |
| 2 | Refactor into `PythonAnalyzer`; `cli.py` delegates to it | Medium | TBD |
| 3 | Rename Python-specific fields to generic names (549 refs) | Medium | TBD |
| 4 | Update `quality_profile.py` and `cli.py` to generic names | Small | TBD |

**Exit criteria:** `make check` passes, `ht check` and `ht report` produce identical scores, zero code duplication in tool invocation.

---

## Milestone 5: Multi-Language

Per HUA-2129-PRP Phase 5–6. Blocked on Milestone 4 completion.

| Phase | What | Effort | CHG |
|---|---|---|---|
| 5 | `TypeScriptAnalyzer` with batch processing | Medium-Large | TBD |
| 6 | Integration testing on mixed-language projects | Small | TBD |

**Exit criteria:** `ht check src/` works on a project with `.py` and `.ts` files, producing quality profiles for both.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
