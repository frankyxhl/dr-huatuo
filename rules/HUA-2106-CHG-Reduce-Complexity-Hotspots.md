# CHG-2106: Reduce Complexity Hotspots

- **Date:** 2026-03-20
- **Requested by:** Frank
- **Status:** Completed
- **Priority:** Medium
- **Change Type:** Normal
- **Scheduled:** 2026-03-20
- **Related:** HUA-2104-SOP (Decision Tree branch 4 — report rendering change)

---

## What

Reduce cyclomatic complexity of two hotspots in `code_reporter.py`:
- `render_html` (complexity 22, grade D) → target ≤10
- `analyze_project` (complexity 19, grade C) → target ≤10

Additionally, remove the dead code block `score_ranges` computed at line ~912 but never used in any renderer.

---

## Why

`render_html` at complexity 22 triggers the scoring penalty (>10 deducts points, >20 is flagged HIGH priority). `analyze_project` at 19 is close behind. Together they drag `code_reporter.py` to 69/100. Reducing complexity improves the project's quality score and makes the code easier to modify.

---

## Impact Analysis

- **Systems affected:** `code_reporter.py` — internal method extraction and dead code removal. Public API unchanged. New helper methods added. `tests/test_reporter_render.py` — new tests for `analyze_project` output and `render_html` structural invariants.
- **Channels affected:** None — all output formats unchanged
- **Downtime required:** No
- **Rollback plan:** `git revert` the commit.

---

## Implementation Plan

1. **Remove dead code:** Delete the `score_ranges` computation block in `render_html` (~line 912) — it is computed but never rendered in the HTML template.

2. **Refactor `render_html` (22 → ≤10):** Extract data preparation into private methods that return **data dicts/lists** (not HTML strings — HTML assembly stays in `render_html`):
   - `_prepare_grade_chart_data(report) -> dict` — returns `{labels, values, colors}`
   - `_prepare_complexity_ranges(report) -> dict` — returns complexity distribution counts
   - `_prepare_actions(report) -> list[dict]` — returns action items with priority/text
   - `_prepare_files_json(report) -> str` — returns JSON string for JS template
   - Keep `render_html` as the template assembler that interpolates prepared data

3. **Refactor `analyze_project` (19 → ≤10):** Extract into focused helpers:
   - `_collect_python_files(path: Path, exclude: list[str]) -> list[Path]` — rglob + exclusion filter
   - `_aggregate_report(report: ProjectReport) -> None` — compute avg_score, avg_complexity, max_complexity, total_violations, total_type_errors, total_security_issues, grade_distribution, complexity_hotspots, security_hotspots, type_hotspots

4. Run `.venv/bin/radon cc code_reporter.py -s -n C` — verify no function above complexity 10

5. Run `make check` — verify ruff + pytest pass

6. **New automated tests:**
   - Test `_collect_python_files` returns expected file list, excludes `.venv/` etc.
   - Test `_aggregate_report` computes correct summary from known `FileMetrics` (avg_score, max_complexity, grade_distribution, totals)
   - Test `render_html` structural invariants:
     - Contains `<canvas id="gradeChart">` and `<canvas id="complexityChart">`
     - Contains `class="score-card"` and `class="section-card"`
     - Contains `id="files-data"` (JSON blob for JS) — parse as valid JSON, verify contains file entries
     - Contains `id="files-body"` (table body)
     - Contains `new Chart(` (Chart.js initialization)
     - Chart data arrays match expected values from the report (e.g., grade distribution counts)
   - Test `_aggregate_report` with known data: verify grade_distribution counts, hotspot sorting (descending by complexity), top-10 truncation for hotspot lists
   - Test `_aggregate_report` edge case: empty report (0 files) — no division-by-zero, empty grade_distribution, all totals at 0
   - Test `_collect_python_files` preserves current exclude semantics (`any(ex in p.parts ...)`) and returns a sorted list (lexicographic order)
   - Test `_prepare_actions` returns expected priority/text dicts matching report state (e.g., max_complexity > 20 → high priority action)
   - Test `_prepare_files_json` is schema-aware: `json.loads` result is a list of dicts, each containing summary keys (`path`, `score`, `max_complexity`, `ruff_violations`, `mypy_errors`, `bandit_high`, `bandit_medium`, `line_count`) AND detail keys (`full_path`, `complexity_hotspots`, `ruff_issues`, `mypy_issues`, `bandit_issues`) used by the UI expand feature
   - Test `_prepare_grade_chart_data` returns correct label/value/color ordering: labels=["A","B","C","D","F"], values match grade_distribution counts, colors in green-to-red order
   - Test complexity bucket boundaries: cc values at 5/6, 10/11, 20/21, 50/51 land in correct buckets
   - Test action thresholds: max_complexity at 20/21, total_security_issues at 0/1, total_type_errors at 5/6, total_violations at 20/21, avg_score at 69.9/70
   - One deterministic `analyze_project` integration test: monkeypatch `analyze_file` to return known `FileMetrics`, verify `_collect_python_files` + `_aggregate_report` are wired together correctly
   - Hotspot ordering: security/type hotspots preserve collection order (current behavior at lines 205-206), complexity hotspots sorted descending
   - Note: the remaining template body in `render_html` is intentionally left as one f-string assembler — further splitting the HTML template itself is out of scope for this CHG

7. Run format smoke tests (verify output is parseable and non-empty, not byte-identical — timestamps and ordering may vary):
   - `.venv/bin/python code_reporter.py . -f json` — parses as valid JSON, same top-level keys
   - `.venv/bin/python code_reporter.py . -f markdown` — contains expected section headers
   - `.venv/bin/python code_reporter.py . -f html -o /tmp/test.html` — file is non-empty, opens in browser

Note: this change reduces the complexity *score* (radon metric), not the overall template size. The f-string template body remains large but has fewer branch points per method.

---

## Testing / Verification

- `.venv/bin/radon cc code_reporter.py -s -n C` reports no functions above complexity 10
- `make check` passes (0 lint violations, all tests pass including new ones)
- JSON output: same top-level keys and values as before refactor
- Markdown output: same section headers as before refactor
- HTML output structural invariants: `<canvas id="gradeChart">`, `<canvas id="complexityChart">`, `class="score-card"`, `class="section-card"`, `id="files-data"` (parseable JSON with schema), `id="files-body"`, `new Chart(`, tab elements, hotspot sections
- `_prepare_files_json` schema verified: list of dicts with expected keys
- Complexity buckets and action thresholds tested at boundaries
- Hotspot ordering preserved: complexity descending, security/type in collection order
- New helper methods have direct unit tests
- One `analyze_project` integration test with monkeypatched `analyze_file`
- **Rollback verification:** After `git revert`, complexity returns to 22/19

---

## Approval

- [x] Reviewed by: Codex (9.2/10 R7), Gemini (10/10 R6)
- [x] Approved on: 2026-03-21

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
| 2026-03-20 | R1 revision: remove dead score_ranges code, helpers return data dicts not HTML, added automated tests for new helpers and HTML structural markers, specify _aggregate_report fields, before/after comparison verification | Frank + Claude Code |
| 2026-03-20 | R2 revision: specified exact HTML structural invariants (canvas IDs, class names, JS markers), clarified template body is intentionally one f-string (out of scope to split), _aggregate_report owns all aggregation state | Frank + Claude Code |
| 2026-03-20 | R3 revision: added files-data JSON parsing test, chart data value verification, empty-report edge case for _aggregate_report, _collect_python_files exclude semantics preservation, renamed visual check to smoke test | Frank + Claude Code |
| 2026-03-20 | R4 revision: added grade_distribution/hotspot sorting/top-10 truncation test targets, _prepare_actions and _prepare_files_json tests, defined smoke test as parseable+non-empty, clarified score vs size tradeoff | Frank + Claude Code |
| 2026-03-21 | R5 revision: schema-aware files_json test, complexity bucket boundary tests, action threshold boundary tests, analyze_project integration test with monkeypatch, specified hotspot ordering behavior, enumerated full HTML invariant list | Frank + Claude Code |
