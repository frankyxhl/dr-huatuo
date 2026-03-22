# CHG-2108: Restore Accidentally Deleted example_code.py

**Applies to:** HUA project
**Last updated:** 2026-03-21
**Last reviewed:** 2026-03-21
**Status:** Completed
**Date:** 2026-03-21
**Requested by:** Frank
**Priority:** High
**Change Type:** Standard

---

## What

Restore `example_code.py` which was accidentally deleted in commit f021239 ("Fix type errors, reduce complexity, add quality infrastructure"). The file is the intentionally flawed demo file used to demonstrate the analyzer. Its deletion breaks `make lint` and `make check` with `E902 No such file or directory`.

## Why

`example_code.py` is a core demo artifact referenced in the Makefile lint target. Its deletion was incidental — commit f021239 targeted type errors and complexity, not this file. `make check` is now broken for all contributors.

## Impact Analysis

- **Systems affected:** `example_code.py` (restored), `make lint` / `make check` (unblocked)
- **Rollback plan:** `git rm example_code.py && git commit`

## Implementation Plan

1. `git checkout 2aa2106 -- example_code.py` — restore from initial commit
2. `make check` — verify lint + test pass

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-21 | Initial version | — |
