# PRP-2116: BugsInPy Pipeline Validation

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Related:** HUA-2109-PRP (Dataset Annotator), HUA-2113-PRP (Dataset Dedup)
**Reviewed by:** —

---

## Background

Huatuo has two implemented data preparation modules (`dataset_annotator.py`, `dataset_dedup.py`) with 266 unit tests and code review approval. They have never been run on an external research dataset.

**BugsInPy** (Widyasari et al., 2020) is a benchmark of 493 bugs from 17 Python projects. Each bug provides a buggy commit and a fixed commit, yielding natural **paired samples** — the same file before and after a fix. This makes it ideal for pipeline validation: we can measure whether metrics meaningfully distinguish buggy from fixed code.

BugsInPy's repo (`data/BugsInPy/`, already cloned and tracked in this project) contains only patch files and commit IDs. The actual source files must be extracted by checking out the original project repos.

---

## What Is It?

Two scripts for Phase 2 pipeline validation:
- **`bugsinpy_extract.py`**: extracts buggy/fixed Python source file pairs from BugsInPy into a structured directory + JSONL manifest with pairing metadata
- **`bugsinpy_analysis.py`**: runs annotation + dedup + paired statistical analysis → validation report

Together they answer: **"Do huatuo's metrics produce signals that correlate with known code quality differences?"**

---

## Problem

### 1. Pipeline never validated on external data

Unit tests verify schema and error handling, not whether metrics are **meaningful**. A file scoring 72 vs 88 — is that a real quality difference? Unknown until validated on labeled data.

### 2. BugsInPy requires non-trivial extraction

BugsInPy's repo contains patch files + commit IDs, not source code. BugsInPy ships its own checkout framework (`data/BugsInPy/framework/bin/bugsinpy-checkout`), but it checks out the **entire project working tree** for each bug — creating a full copy of e.g. pandas (~500MB) per bug. For 169 pandas bugs, that's ~85GB. Our extraction approach copies only the **affected `.py` files** (typically 1–4 files per bug), reducing disk usage by 99%+ and extraction time proportionally.

### 3. Pairing metadata needed for paired analysis

The annotator (HUA-2109) outputs JSONL with `path`, `source`, `license` but no `bug_id` or `variant` (buggy/fixed). Paired analysis requires knowing which buggy file corresponds to which fixed file. This PRP defines a **manifest-based** approach: the extractor produces a JSONL manifest with pairing metadata, and the annotator's "all other fields preserved verbatim" contract propagates it through.

---

## Scope

**In scope (v1 — single project: `thefuck`, 32 bugs):**
- `bugsinpy_extract.py`: extract buggy/fixed file pairs, produce manifest with pairing metadata
- `bugsinpy_analysis.py`: annotate + dedup + paired analysis + validation report
- Test file exclusion policy (filter `test_*.py`, `*_test.py`, paths containing `/tests/`)
- Multi-file bug handling (thefuck bug 16 has 4 affected files)
- Paired analysis using Cohen's d effect size on standardized metric deltas
- `--project` flag to select BugsInPy project
- Analysis report in terminal + markdown

**Out of scope (v1):**
- All 17 BugsInPy projects (deferred until single-project validation passes)
- Model training (Phase 3)
- Statistical significance testing beyond effect sizes
- Visualization / charts

---

## Proposed Solution

### Module 1: `bugsinpy_extract.py`

```python
BugsInPyExtractor
  __init__(bugsinpy_root="data/BugsInPy", output_root="data/bugsinpy",
           project="thefuck", exclude_tests=True)
  extract_all() -> ExtractionReport
  _clone_or_reuse_project() -> Path        # cached in data/repos/<project>/
  _get_affected_files(buggy_commit, fixed_commit) -> list[str]  # git diff --name-only
  _is_test_file(path) -> bool              # test_*.py, *_test.py, /tests/
  _extract_bug(bug_id, bug_dir) -> BugExtractionResult | None
```

**Why not use `bugsinpy-checkout`?** It checks out the entire project working tree per bug (e.g., 500MB for pandas × 169 bugs = ~85GB). Our approach: clone once, `git show <commit>:<path>` to extract only affected files. Disk usage: ~1MB per bug instead of ~500MB.

**Extraction flow:**
```
For each bug in projects/<project>/bugs/<N>/:
  1. Read bug.info → buggy_commit_id, fixed_commit_id
  2. In cached clone: git diff --name-only buggy_commit fixed_commit → list of changed paths
     - Filter to .py files only
     - Exclude test files if exclude_tests=True (test_*.py, *_test.py, /tests/)
     - Multi-file bugs: ALL affected non-test .py files extracted
  3. For each affected file:
     - git show buggy_commit:<path> > data/bugsinpy/<project>/buggy/bug_<N>/<path>
     - git show fixed_commit:<path> > data/bugsinpy/<project>/fixed/bug_<N>/<path>
  4. Write manifest entry (see Manifest schema below)
```

**Skip conditions:**
- `git show` fails (file didn't exist at that commit) → skip file, record in `skip_reasons`
- No non-test `.py` files affected → skip entire bug
- Clone/checkout fails → skip entire bug

**ExtractionReport:**
```python
@dataclass
class ExtractionReport:
    project: str
    total_bugs: int
    extracted_bugs: int
    skipped_bugs: int
    total_buggy_files: int
    total_fixed_files: int
    multi_file_bugs: int        # bugs with >1 affected source file
    test_files_excluded: int
    skip_reasons: dict[int, str]
```

### Manifest schema

The extractor produces a JSONL manifest at `data/bugsinpy/<project>/manifest.jsonl`. Each line is one file (not one bug — multi-file bugs produce multiple lines):

```json
{
  "bug_id": 1,
  "project": "thefuck",
  "variant": "buggy",
  "path": "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip_unknown_command.py",
  "source": "BugsInPy",
  "license": "MIT",
  "buggy_commit": "2ced7a7f...",
  "fixed_commit": "444908ce...",
  "affected_file": "thefuck/rules/pip_unknown_command.py"
}
```

**Pairing join key — path-based reconstruction:** The directory structure encodes pairing metadata in the file path:

```
data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip_unknown_command.py
                      ^^^^^ ^^^^^  ← variant + bug_id parsed from path
```

The analysis script reconstructs `bug_id` and `variant` from the annotated JSONL's `path` field using regex: `r".*/(?P<variant>buggy|fixed)/bug_(?P<bug_id>\d+)/(?P<affected_file>.+)$"`. This avoids depending on manifest field propagation through the annotator.

**Note:** HUA-2109-PRP specifies "All other fields preserved verbatim" for manifest input, but the current implementation of `annotate_manifest()` only reads `path`, `source`, `license`. This is an annotator implementation gap — tracked as a follow-up fix. This PRP does NOT depend on that fix.

The extractor produces **two manifests**: `manifest_buggy.jsonl` and `manifest_fixed.jsonl`, each fed to `dataset_annotator.py` as manifest input. The manifests include `bug_id`, `variant`, `affected_file` for traceability, but the analysis script reconstructs pairing from paths, not from annotator output fields.

### Module 2: `bugsinpy_analysis.py`

```python
BugsInPyAnalysis
  __init__(data_root="data/bugsinpy", project="thefuck")
  run() -> AnalysisReport
  _annotate(manifest_path, output_path) -> Path
  _dedup_within(jsonl_path) -> tuple[Path, DeduplicationReport]
  _dedup_cross(buggy_jsonl, fixed_jsonl) -> float   # returns overlap rate
  _paired_analysis(buggy_jsonl, fixed_jsonl) -> PairedResults
  _render_report(report) -> str                      # markdown
```

**Integration method:** imports `DatasetAnnotator` and `DatasetDeduplicator` directly (Python API, not subprocess) for better error propagation and type safety.

**Analysis pipeline:**
```
1. Annotate buggy manifest → buggy_annotated.jsonl
2. Annotate fixed manifest → fixed_annotated.jsonl
3. Dedup within-buggy → buggy_deduped.jsonl + within-buggy dedup rate
4. Dedup within-fixed → fixed_deduped.jsonl + within-fixed dedup rate
5. Cross-split overlap check (informational only, NOT filtering):
   - Run dedup with --ref=fixed on buggy → report overlap rate
   - Expected to be HIGH (buggy/fixed are intentionally near-neighbors)
   - This validates that dedup correctly detects near-duplicates
6. Paired analysis on annotated (pre-dedup) data:
   - Parse (bug_id, variant, affected_file) from each record's path via regex
   - Join buggy↔fixed on (bug_id, affected_file)
   - For each metric: compute delta = fixed_value - buggy_value
   - Exclude records where either side has error_type != null
   - Exclude metrics with >30% null rate (environment-sensitive)
7. Generate report
```

**Cross-split dedup clarification:** This is **informational only** — it measures the near-duplicate detection rate between buggy and fixed files, NOT a filtering step. Since buggy/fixed versions of the same file differ by only a few lines, the overlap rate should be high (~80–95%). If it's low, it indicates a problem with the dedup pipeline's sensitivity.

### Analysis report

| Section | Content | Method |
|---|---|---|
| Extraction summary | Bugs extracted, files per side, skip rate, test files excluded | ExtractionReport |
| Annotation summary | Success rate, `error_type` distribution, `tool_errors` rate, `data_warnings` rate | Count/percentage |
| Score distribution | Mean/median/std/min/max for buggy vs fixed | `statistics` module |
| Paired metric deltas | For each numeric metric: mean delta, median delta, % where fixed > buggy (sign consistency) | Paired difference |
| Top discriminative metrics | Metrics ranked by **Cohen's d** on paired deltas (standardized effect size) | `mean(delta) / std(delta)` |
| Metric exclusions | Metrics excluded due to >30% null rate; `suspect:mypy_env` rate | Null analysis |
| Near-duplicate rates | Within-buggy, within-fixed, cross-split (informational) | DeduplicationReport |
| Conclusion | Does the pipeline produce meaningful quality signals? Which metrics are most/least useful? | Narrative |

**Cohen's d** is used instead of raw deltas because metrics have different scales (`ruff_violations` 0–50 vs `halstead_volume` 0–10000). Cohen's d normalizes by standard deviation: `|d| > 0.8` = large effect, `0.5–0.8` = medium, `0.2–0.5` = small.

### CLI

```bash
# Extract thefuck bugs (32 bugs → ~60 file pairs)
python bugsinpy_extract.py --project thefuck

# Run full analysis
python bugsinpy_analysis.py --project thefuck

# Extract without test files (default) / with test files
python bugsinpy_extract.py --project thefuck --include-tests

# Extract a different project
python bugsinpy_extract.py --project scrapy
python bugsinpy_analysis.py --project scrapy
```

### Directory structure

```
data/                                  # partially gitignored (see Impact)
├── BugsInPy/                          # ALREADY TRACKED in git (BugsInPy metadata repo)
├── repos/                             # GITIGNORED — cached project clones
│   └── thefuck/                       # git clone of thefuck
├── bugsinpy/                          # GITIGNORED — extracted files + results
│   └── thefuck/
│       ├── buggy/
│       │   ├── bug_1/
│       │   │   └── thefuck/rules/pip_unknown_command.py
│       │   └── bug_16/               # multi-file bug
│       │       ├── thefuck/conf.py
│       │       ├── thefuck/shells/bash.py
│       │       └── ...
│       ├── fixed/
│       │   └── ...
│       ├── manifest_buggy.jsonl
│       ├── manifest_fixed.jsonl
│       ├── buggy_annotated.jsonl
│       ├── fixed_annotated.jsonl
│       └── analysis_report.md
```

### Dependencies

No new dependencies. Uses existing `dataset_annotator.py`, `dataset_dedup.py`, and standard library (`subprocess`, `shutil`, `pathlib`, `statistics`).

### Impact

- **New files:** `bugsinpy_extract.py`, `bugsinpy_analysis.py`
- **New tests:** `tests/test_bugsinpy_extract.py` (patch parsing, test file exclusion, multi-file bug handling, skip conditions, manifest schema), `tests/test_bugsinpy_analysis.py` (paired join logic, Cohen's d computation, null exclusion, report generation)
- **`.gitignore`:** add `data/repos/` and `data/bugsinpy/` (NOT `data/` or `data/BugsInPy/` — the latter is already tracked)
- **Makefile:** add both scripts to `lint` and `fmt` targets
- **CLAUDE.md:** add usage note
- **Existing modules:** no changes

---

## Open Questions

_All open questions resolved before review._

1. **Why not use BugsInPy's `bugsinpy-checkout`?** It checks out the full project working tree per bug (hundreds of MB per checkout). Our `git show <commit>:<path>` approach extracts only affected files (~1KB–50KB per file). For thefuck (32 bugs): ~2MB vs ~1.6GB. For pandas (169 bugs): ~10MB vs ~85GB.

2. **Why start with thefuck?** 32 bugs, small project, fast extraction. Bug 16 is multi-file (4 files), validating multi-file handling. Bugs are mostly in source files (not just tests), so filtered output is still meaningful.

3. **How are buggy↔fixed files paired?** Via **path-based reconstruction**: the directory structure `buggy/bug_<N>/<file>` and `fixed/bug_<N>/<file>` encodes `variant`, `bug_id`, and `affected_file` in the path. The analysis script extracts these via regex from the annotated JSONL's `path` field. This avoids depending on manifest field propagation through the annotator (which currently drops extra fields — tracked as a separate annotator bug fix).

4. **Why exclude test files?** Bug patches often include both source fixes and test additions/modifications. Test files have different metric characteristics (higher assertion density, lower complexity) that would skew the source-quality comparison. Default: exclude. `--include-tests` flag for completeness.

5. **What if buggy and fixed score the same?** A valid and informative finding. BugsInPy bugs are mostly logic errors, not style issues. If static metrics don't distinguish them, that's useful signal for Phase 3: it means we'd need semantic features (code embeddings), not just static metrics, for bug detection.

6. **Why is cross-split dedup informational only?** Buggy and fixed versions of the same file are intentionally near-identical (differ by a few lines). Dedup detecting them as near-duplicates validates the dedup pipeline's sensitivity. Filtering them out would defeat the purpose of paired analysis.

7. **Why Cohen's d instead of raw deltas?** Metrics have wildly different scales (`ruff_violations` 0–50, `halstead_volume` 0–10000). Cohen's d standardizes by dividing by the pooled standard deviation, making effect sizes comparable across metrics. `|d| > 0.8` = large effect.

---

## Review

- [x] Reviewer 1 (Codex): 9.2 / 10 — APPROVED (v3, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9.5 / 10 — APPROVED (v1, 2026-03-22)
- [x] Approved on: 2026-03-22

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v3: Fixed critical pairing issue — path-based reconstruction instead of manifest field propagation (annotator drops extra fields); normalized extraction narrative to git diff --name-only only; documented annotator field-preservation gap as follow-up | Claude Code |
| 2026-03-22 | v2: Addressed Codex rejection (6.1/10) — added manifest-based pairing with (bug_id, affected_file) join key; test file exclusion policy; git show extraction (justified vs bugsinpy-checkout); corrected gitignore (data/repos/ + data/bugsinpy/ only); added tests for analysis script; defined Cohen's d for discriminative metrics; clarified cross-split dedup as informational; used git diff --name-only instead of patch parsing | Claude Code |
| 2026-03-22 | v1: Initial version | Claude Code |
