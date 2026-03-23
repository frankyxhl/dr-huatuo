# ADR-2130: Unify Scoring to Strictest Standard

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Accepted

---

## What Is It?

Decision to unify the two divergent scoring formulas in `code_analyzer.py` and `code_reporter.py` to the stricter parameters from `code_analyzer.py`.

---

## Context

Two independent `CodeAnalyzer` classes exist with different scoring:

| Parameter | `code_analyzer.py` (ht check) | `code_reporter.py` (ht report) |
|---|---|---|
| Complexity deduction | `(cc-10) × 5`, cap 20 | `(cc-10) × 3`, cap 25 |
| Pylint | Yes (5 tools) | No (4 tools) |
| Grade labels | `"A (Excellent)"`, `"B (Good)"`, etc. | `"A"`, `"B"`, etc. |

This divergence was historical (two modules evolved independently). Users running `ht check` and `ht report` on the same file get different scores, which is confusing.

## Decision

Unify both to the **strictest** standard (`code_analyzer.py` parameters):

1. **Complexity:** `(cc-10) × 5`, cap 20 — apply to `code_reporter.py`
2. **Pylint:** Add pylint to `code_reporter.py` (5 tools, same as check)
3. **Grade labels:** Use descriptive labels `"A (Excellent)"`, `"B (Good)"`, `"C (Fair)"`, `"D (Pass)"`, `"F (Fail)"` in both
4. **Principle:** `ht check` and `ht report` must produce identical scores for the same file

## Consequences

**Positive:**
- Users see consistent scores regardless of which command they run
- Single source of truth for "what is good code quality"
- Eliminates confusion when check and report disagree

**Negative:**
- `ht report` scores will drop for files with high complexity (stricter formula)
- Existing HTML reports regenerated after this change will show lower scores
- Adding pylint to `code_reporter.py` increases analysis time slightly

**Migration:** No backward compatibility needed — scores are display-only, not persisted as contracts. Users may notice lower scores in reports after upgrade.

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version — accepted | Frank + Claude Code |
