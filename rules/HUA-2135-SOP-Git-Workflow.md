# SOP-2134: Git Workflow

**Applies to:** HUA project
**Last updated:** 2026-03-23
**Last reviewed:** 2026-03-23
**Status:** Active

---

## What Is It?

The git branching and PR workflow for all code changes in the HUA project. All changes go through feature branches and pull requests — no direct commits to main.

## Why

Direct commits to main bypass review gates and make it hard to revert individual changes. PRs provide a clear audit trail, enable CI checks before merge, and align with the Codex+Gemini review SOP (COR-1602).

---

## When to Use

- Any code, configuration, script, or documentation change
- Standalone documentation-only changes (rules/, CLAUDE.md, etc.)
- Version bumps, releases, and release-preparation changes

## When NOT to Use

- See Emergency Exception below

## Steps

1. **Create feature branch** from main
   ```bash
   git checkout main && git pull origin main
   git checkout -b <type>/<short-description>
   ```
   Branch naming: `feature/<desc>`, `fix/<desc>`, `release/v<X.Y.Z>`, `hotfix/<desc>`, `docs/<desc>`

2. **Develop on the branch** — commit as you go, following the change workflow (COR-1101 CHG → COR-1602 review → implement → code review per COR-1610)

3. **Push to the feature branch** (never to main)
   ```bash
   git push -u origin <type>/<description>
   ```

4. **Check README** — if the change affects user-facing features, CLI, or installation, update `README.md` in the same branch

5. **Create PR** when code review passes (Codex+Gemini ≥ 9)
   ```bash
   gh pr create --base main --head <type>/<description>
   ```
   PR body must include: summary, review scores, test plan

6. **CI must pass** — wait for GitHub Actions (test + lint + format) to go green

7. **Merge** — after user explicitly approves, enable auto-merge:
   ```bash
   gh pr merge <number> --auto --squash
   ```
   This sets the PR to auto-merge once all CI status checks pass. Prerequisites before requesting user approval:
   - Review scores meet the Codex+Gemini ≥ 9 threshold
   - The branch is up to date with main (no conflicts)
   - **The user has explicitly approved the merge** — agent must never run `gh pr merge` on its own

   Merge method: **squash merge** (default, keeps main history linear). Use `--merge` only when individual commit history is needed (e.g., multi-phase work).

8. **Clean up**
   ```bash
   git checkout main && git pull origin main
   git branch -D <type>/<description>  # -D required after squash merge
   git push origin --delete <type>/<description>
   ```

## Rules

- **No direct commits to main** — all changes go through PRs
- **No auto-push** — agent never pushes without explicit user approval
- **No auto-merge** — agent never merges PRs without explicit user approval
- **CI must pass before merge** — no merging red PRs
- **One PR per logical change** — don't bundle unrelated changes
- **PR title under 70 chars** — details go in the body

## Emergency Exception

Emergency hotfixes may bypass the feature-branch requirement only for COR-1101 emergency changes.

- **Approval authority:** repository owner
- **Required record:** incident/change ID, reason for bypass, affected commit(s)
- **Backfill:** open a PR by the next business day to document the change and complete normal review

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-23 | Initial version | Frank + Claude Code |
| 2026-03-23 | R1 revision: add emergency exception section, explicit merge criteria, expand When to Use scope, cite SOP IDs in Step 2, add branch naming conventions (hotfix/docs), squash merge as default, add remote branch deletion to cleanup | Claude Code |
| 2026-03-30 | Add "No auto-merge" rule: agent must never merge PRs without explicit user approval | Claude Code |
| 2026-03-30 | Update Step 7: use `gh pr merge --auto --squash` for CI-gated auto-merge | Claude Code |
