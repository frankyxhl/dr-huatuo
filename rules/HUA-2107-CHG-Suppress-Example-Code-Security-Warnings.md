# CHG-2107: Suppress Example Code Security Warnings

- **Date:** 2026-03-20
- **Requested by:** Frank
- **Status:** Rejected
- **Priority:** Low
- **Change Type:** Normal
- **Scheduled:** 2026-03-20
- **Related:** —

---

## What

Add bandit inline suppression comments (`# nosec`) to the intentionally insecure code in `example_code.py`. This file exists as a demo of bad code patterns for the analyzer — the security issues are by design, not bugs.

Specifically:
- `eval(expr)` on line 10 — add `# nosec B307`
- `DB_PASSWORD = "admin123"` on line 64 — add `# nosec B105`

---

## Why

`example_code.py` is an intentionally flawed sample file used to demonstrate the analyzer. Bandit correctly flags it, but these warnings inflate the project's security issue count (1 MEDIUM, 1 LOW). Suppressing with `# nosec` acknowledges the issues are known and intentional, removing noise from the project's own quality report without hiding real security problems.

---

## Impact Analysis

- **Systems affected:** `example_code.py` only — two comment additions
- **Channels affected:** None
- **Downtime required:** No
- **Rollback plan:** Remove the `# nosec` comments.

---

## Implementation Plan

1. Add `# nosec B307` to `eval(expr)` line in `example_code.py`
2. Add `# nosec B105` to `DB_PASSWORD = "admin123"` line in `example_code.py`
3. Run `PATH=".venv/bin:$PATH" .venv/bin/bandit -r example_code.py` — verify 0 issues
4. Run `make check` — verify lint + test still pass

---

## Testing / Verification

- `bandit -r example_code.py` reports 0 issues (previously 2)
- `make check` passes
- `# nosec` comments clearly document the suppression reason
- **Rollback verification:** Remove `# nosec` comments, bandit reports 2 issues again

---

## Approval

- [ ] Reviewed by: —
- [ ] Approved on: —

---

## Execution Log

| Date | Action | Result |
|------|--------|--------|

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | Frank + Claude Code |
| 2026-03-20 | Rejected: example_code.py is intentionally insecure for demo — suppressing defeats the purpose | Frank + Claude Code |
