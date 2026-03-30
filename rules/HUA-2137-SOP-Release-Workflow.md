# SOP-2137: Release Workflow

**Applies to:** HUA project
**Last updated:** 2026-03-30
**Last reviewed:** 2026-03-30
**Status:** Active
**Related:** HUA-2135-SOP (Git Workflow), publish.yml (PyPI automation)

---

## What Is It?

The end-to-end process for releasing a new version of dr-huatuo to PyPI. Covers version bumping, changelog, GitHub Release creation, and automated publishing.

## Why

A repeatable release process prevents version mismatches, missing changelogs, and broken publishes. The publish.yml workflow automates build + PyPI upload on GitHub Release creation, so the SOP focuses on the manual preparation steps.

---

## When to Use

- After merging a feature, fix, or breaking change that should be shipped to users
- For scheduled releases

## When NOT to Use

- Internal-only changes (rules/, docs/, CI config) that don't affect the published package
- Research pipeline changes that are not part of the distributed package

---

## Prerequisites

- All PRs for this release are merged to main
- CI is green on main
- Codex+Gemini review scores >= 9 on all included changes

---

## Steps

### 1. Determine version number

Follow [SemVer](https://semver.org/):
- **MAJOR** (X.0.0): breaking API changes
- **MINOR** (0.X.0): new features, backward compatible
- **PATCH** (0.0.X): bug fixes only

Check current version:
```bash
grep 'version' pyproject.toml | head -1
grep '__version__' src/dr_huatuo/__init__.py
```

### 2. Create release branch

```bash
git checkout main && git pull origin main
git checkout -b release/v<X.Y.Z>
```

### 3. Bump version

Update version in **both** files (must match):
- `pyproject.toml` → `version = "<X.Y.Z>"`
- `src/dr_huatuo/__init__.py` → `__version__ = "<X.Y.Z>"`

### 4. Update README

- Update roadmap checkboxes for completed milestones
- Add/update Quick Start examples if CLI changed
- Update badge versions if applicable

### 5. Update pyproject.toml description

If the scope of the tool changed (e.g., added TypeScript support), update:
- `description` field
- `keywords` list
- `classifiers` if needed

### 6. Run full verification

```bash
make check          # lint + test
ruff format --check src/dr_huatuo/*.py tests/  # format check (CI runs this)
```

All must pass. Do not proceed with failures.

### 7. Commit, push, and create PR

```bash
git add -A
git commit -m "Release v<X.Y.Z>"
git push -u origin release/v<X.Y.Z>
gh pr create --title "Release v<X.Y.Z>" --body "..."
```

Wait for CI to pass. **Do not merge without user approval** (HUA-2135 Rules).

### 8. Merge the release PR

After user approval:
```bash
gh pr merge <number> --squash
```

### 9. Create GitHub Release

Draft release notes in Keep a Changelog format:
```bash
gh release create v<X.Y.Z> --title "v<X.Y.Z> — <short description>" --notes "$(cat <<'NOTES'
## dr-huatuo v<X.Y.Z>

### Added
- ...

### Changed
- ...

### Fixed
- ...

### Upgrade

\`\`\`bash
pip install --upgrade dr-huatuo
\`\`\`

### Full Changelog

https://github.com/frankyxhl/dr-huatuo/compare/v<PREV>...v<X.Y.Z>
NOTES
)"
```

**Do not create the release without user approval.** Creating a GitHub Release triggers publish.yml which automatically publishes to PyPI.

### 10. Verify PyPI publish

After publish.yml completes:
```bash
pip install --upgrade dr-huatuo
ht version
```

Confirm the version matches and basic commands work.

### 11. Clean up

```bash
git checkout main && git pull origin main
git branch -D release/v<X.Y.Z>
git push origin --delete release/v<X.Y.Z>
```

---

## Rules

- **Version must match** in `pyproject.toml` and `__init__.py` — mismatch will cause confusion
- **No auto-release** — agent never creates GitHub Releases without explicit user approval (triggers PyPI publish)
- **No auto-merge** — per HUA-2135 Rules
- **CI must be green** before release PR merge
- **Release notes required** — every release must have a changelog in Keep a Changelog format

## Automation

- **publish.yml** triggers on `release: [published]` event
- Pipeline: test → build (`python -m build`) → publish (PyPI trusted publisher)
- Uses `pypa/gh-action-pypi-publish` with OIDC (no API tokens needed)

## Rollback

If a broken version is published:
1. Yank the version on PyPI: `pip install twine && twine yank dr-huatuo <X.Y.Z>`
2. Fix the issue on main
3. Release a patch version (X.Y.Z+1) following this SOP

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-30 | Initial version | Frank + Claude Code |
