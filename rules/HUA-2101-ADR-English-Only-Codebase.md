# HUA-2101-ADR-20260320D1: English Only Codebase

- **Date:** 2026-03-20
- **Status:** Accepted
- **Related:** COR-1401 (Documentation Language Policy)

---

## Context

The existing codebase uses Chinese for all comments, docstrings, and UI strings (e.g., `"📊 代码质量分析报告"`, `"A (优秀)"`). As the project grows and potentially gains contributors, a consistent language policy is needed.

---

## Options Considered

- **Option A:** Keep Chinese — natural for current author, but limits contributor pool and tool compatibility
- **Option B:** English only — all new code in English, migrate existing code separately
- **Option C:** Mixed — English for code/comments, Chinese for user-facing strings — adds complexity, unclear boundary

---

## Decision

All code must be written in English from this point forward. This includes comments, docstrings, variable names, log messages, error messages, and new user-facing output strings.

Existing Chinese code will be migrated to English in a separate CHG.

---

## Rationale

- Consistent with COR-1401 (Documentation Language Policy) which requires English for all documents
- Broader contributor accessibility
- Better compatibility with static analysis tools and AI code assistants
- Single language eliminates ambiguity about when to use which

---

## Consequences

- All new code must be written in English
- CLAUDE.md updated to enforce this rule
- A separate CHG is needed to migrate existing Chinese in `code_analyzer.py`, `code_reporter.py`, and `example_code.py`
- User-facing report strings (grade labels, section headers) will change — this is a breaking change for anyone parsing text output

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
