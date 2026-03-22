# SOP-2104: Workflow Routing PRJ

**Applies to:** HUA project
**Last updated:** 2026-03-21
**Last reviewed:** 2026-03-20
**Status:** Active

---

## What Is It?

Project-level workflow routing supplement for the huatuo code quality analysis toolkit. Adds project-specific decision branches and golden rules on top of COR-1103 (PKG) and ALF-2207 (USR).

---

## Project Decision Tree

After routing through COR-1103, check these HUA-specific branches:

```
1. Changing scoring formula or grade thresholds?
   └── ADR (COR-1100) to record rationale
       └── CHG (COR-1101) to implement
       └── Update BOTH analyzers while preserving intentional divergence
           (code_analyzer: x5/cap20, code_reporter: x3/cap25)
           unless the ADR explicitly changes it
       └── Update affected test assertions in tests/

2. Adding a new analysis tool? (e.g., pyright, vulture)
   └── If it affects scoring → ADR (COR-1100) first, then:
   └── PRP (COR-1102) → Review (COR-1602 strict)
       └── Touch points: dataclass fields, _run_xxx() method,
           _check_tools(), _calculate_score() (if score-affecting),
           print_report() (code_analyzer), all renderers (code_reporter)
       └── Note: code_analyzer.py checks 5 tools (incl. pylint),
           code_reporter.py checks only 4 (no pylint) — decide
           which analyzer(s) get the new tool

3. Bug in tool subprocess parsing?
   └── CHG (COR-1101)
       └── Check if BOTH CodeAnalyzer classes have the same bug
       └── Note tool asymmetry: code_analyzer.py runs pylint,
           code_reporter.py does NOT

4. Report rendering change?
   ├── HTML → CHG (COR-1101)
   │   └── render_html (~900 lines) + 7 helper methods
   │       (_generate_complexity_rows, _generate_complexity_rows_with_expand,
   │        _generate_complexity_details_html, _generate_breakdown_content,
   │        _generate_security_table, _generate_actions_html,
   │        _generate_files_rows)
   │       Total HTML surface: ~1140 lines
   │   └── Verify visually — no unit test coverage for HTML output
   ├── Terminal (rich) → CHG (COR-1101)
   │   └── render_terminal + _render_* helper methods
   │   └── Verify visually — no unit test coverage
   ├── JSON → CHG (COR-1101) with breaking-change flag
   │   └── JSON field names are a contract for downstream consumers
   │   └── Update tests/test_reporter_render.py assertions
   └── Markdown → CHG (COR-1101)
       └── Update tests/test_reporter_render.py assertions

5. CLI argument or interface change?
   └── CHG (COR-1101) with breaking-change flag
       └── code_analyzer.py: bare sys.argv[1] (positional path only)
       └── code_reporter.py: argparse with positional path + -f, -o, -e flags
       └── Changes to either CLI are breaking for users

6. Refactoring shared code between the two analyzers?
   └── PRP (COR-1102) → Review (COR-1602 strict)
       └── Scoring divergence is intentional; do NOT unify
           unless explicitly directed by an ADR
       └── This is architectural — affects scoring consistency

7. Build/config change? (Makefile, pyproject.toml, dependencies)
   └── CHG (COR-1101)
       └── Verify make check still passes after changes
       └── If adding dependencies, update CLAUDE.md

8. Changing example_code.py?
   └── CHG (COR-1101)
       └── This file is intentionally flawed for demo purposes
       └── Covered by make lint — must remain lint-clean

9. Research / dataset work? (analyzing external Python code datasets)
   ├── New research direction or new module/component needed?
   │   └── PRP (COR-1102) → Review (COR-1602 strict)
   ├── Incomings research report (raw input from external LLMs/research)?
   │   └── Drop into incomings/ as-is — read-only reference material
   │   └── Create a PRP (COR-1102) to propose how to act on the report
   ├── Analysis script or experiment that uses the existing analyzers?
   │   └── CHG (COR-1101)
   │       └── Scripts must pass make lint if added to Makefile scope
   │       └── Do NOT modify core analyzer scoring for research-only needs
   └── Dataset pipeline or new output format for research consumers?
       └── PRP (COR-1102) → Review (COR-1602 strict)
           └── JSON output changes are breaking — flag as such
```

---

## Project Golden Rules

```
Scoring formula = project identity; any change requires an ADR with rationale
Two CodeAnalyzer classes exist with DIFFERENT parameters and tool sets:
  code_analyzer.py: 5 tools (incl. pylint), complexity x5/cap20, grade "A (Excellent)"
  code_reporter.py: 4 tools (no pylint), complexity x3/cap25, grade "A"
  This divergence is intentional — always check both, preserve asymmetry
HTML rendering = render_html + 7 helpers (~1140 lines total); test visually
JSON output is a contract; field changes are breaking changes
CLI interfaces differ between the two scripts; changes are breaking
All code must be in English (HUA-2101-ADR)
make check (lint + test) must pass before any change is complete
```

---

## Project Context

- **Prefix:** HUA
- **Python:** 3.13, venv at `.venv/`
- **Analysis tools:** ruff, radon, bandit, mypy (both analyzers), pylint (code_analyzer.py only)
- **Test entry point:** `make test` (139 tests via pytest)
- **Lint entry point:** `make lint` (ruff, rules E/F/W/I, covers code_analyzer.py, code_reporter.py, example_code.py, tests/)
- **Key documents:**
  - HUA-2100-PRP: Test infrastructure design (Implemented)
  - HUA-2101-ADR: English-only codebase policy (Accepted)
  - HUA-2102-CHG: Test infrastructure implementation (Completed)
  - HUA-2103-CHG: Ruff violations + English migration (Completed)
  - HUA-2105-CHG: Fix type errors (Completed)
  - HUA-2106-CHG: Reduce complexity hotspots (Completed)
  - HUA-2108-CHG: Restore accidentally deleted example_code.py (Completed)

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
| 2026-03-20 | R1 revision: fix HTML line count (~1140 not ~800), add helper methods, add terminal/CLI/build/example branches, note pylint asymmetry, clarify scoring divergence is intentional, split "add new tool" into score-affecting vs not | Frank + Claude Code |
| 2026-03-20 | R2 revision: correct helper count to 7 with all names listed, add positional path arg to CLI description, add _check_tools and print_report to new-tool touch points | Frank + Claude Code |
| 2026-03-20 | R3 revision: fix golden rules "6 helpers" → "7 helpers" to match decision tree | Frank + Claude Code |
| 2026-03-20 | Approved: Codex 9.5/10 (R4), Gemini 9.6/10 (R2) | Frank + Claude Code |
| 2026-03-21 | Add branch 9 (research/dataset work), fix Python 3.12→3.13, update test count 78→139, add recent CHGs to key documents | Claude Code |
