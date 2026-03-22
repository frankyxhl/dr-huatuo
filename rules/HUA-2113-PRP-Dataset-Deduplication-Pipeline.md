# PRP-2113: Dataset Deduplication Pipeline

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Approved
**Related:** HUA-2109-PRP (Dataset Annotation Pipeline, Approved), HUA-2111-REF (Metrics Research), HUA-2112-REF (Tools Survey)
**Reviewed by:** Codex 9.8/10, Gemini 9.9/10 (2026-03-22); External review incorporated in v4

---

## Background

Huatuo (华佗) is a Python code quality toolkit that orchestrates ruff, bandit, mypy, pylint, and radon to produce per-file quality scores (0–100) and grades (A–F). The project is building an ML dataset labeling pipeline:

- **`dataset_annotator.py`** (HUA-2109-PRP, Approved): batch-annotates external Python files → JSONL with ~25 quality metrics per record (including `path`, `source`, `license`, `score`, `grade`, Halstead, complexity, AST metrics). Note: `content_sha256` is not yet in the annotator schema — a follow-up amendment to HUA-2109-PRP is required (see Impact)
- **`dataset_dedup.py`** (this PRP): deduplicates those datasets before they are used for ML training

The target datasets range from hundreds of files (BugsInPy: 493 bugs, 17 projects) to tens of thousands (CodeSearchNet subsets). v1 is a local single-machine tool; larger-scale streaming is deferred. Near-duplicate rate in GitHub-scraped datasets is typically 5–30%.

**Research basis:** Allamanis (2019) showed test metrics can be inflated up to 100% by code duplication in ML models. BigCode/StarCoder treats near-dedup as standard preprocessing; The Stack v2 uses 5-grams + Jaccard 0.7.

---

## What Is It?

A new module `dataset_dedup.py` that identifies and removes near-duplicate Python files from code datasets. It supports three input modes, two deduplication passes (exact hash + token-level MinHash/LSH with verified Jaccard + Union-Find), and an optional cross-split reference mode to prevent train/test leakage. v1 targets local single-machine use on datasets up to ~100K files.

---

## Problem

### 1. Near-duplicates corrupt ML training data

Studies (Allamanis 2019, BigCode 2023) find 5–30% near-duplicate rates in GitHub-scraped datasets. Consequences:
- **Data leakage**: model memorises training examples when similar files appear in both splits
- **Distribution skew**: overrepresented patterns dominate learned quality signals
- **Wasted annotation compute**: `dataset_annotator.py` runs 5+ tools per file; annotating near-duplicates multiplies cost

### 2. `dataset_annotator.py` does no deduplication

HUA-2109-PRP produces per-file JSONL but does not filter duplicates.

### 3. Exact hash misses the most common near-duplicate pattern

Variable renaming, comment changes, whitespace: all missed by exact hash. Token-level MinHash detects structural copies modulo identifier renaming.

### 4. No existing tool integrates with the huatuo JSONL schema

Generic tools operate on text corpora without the huatuo `source`, `license`, `score`, `grade`, and `content_sha256` fields.

---

## Scope

**In scope (v1 — local single-machine, ≤100K files):**
- Normalized-content exact hash deduplication (SHA-256 after line-ending + trailing-whitespace normalisation; not raw-bytes exact — see trade-off note)
- Token-level MinHash + LSH with candidate Jaccard verification (using `tokenize.open()` + `datasketch`)
- LSH parameters auto-computed by `datasketch` from `threshold` (not hardcoded)
- Configurable Jaccard similarity threshold (default: 0.8 — conservative; see Open Questions #3)
- Two keep strategies: `canonical_path` (lexicographically smallest path, deterministic), `best_score` (label-biased opt-in; see notes)
- Cross-split reference deduplication (`--ref`) with separate exact/near mechanisms
- Three input modes: raw `.py` directory, annotated JSONL (with `content_sha256` validation), unannotated JSONL manifest
- `--workers N` parallelism for MinHash signature computation
- `--dry-run` mode (report without writing output)
- Explicit failure contract for all error modes

**Out of scope (v1):**
- Streaming / distributed processing for >100K files — deferred; see Architecture Notes
- Code embedding / vector database (semantic deduplication) — deferred
- AST-level normalisation (CFG canonicalisation) — too expensive
- Multi-language support (Python only)
- Combined annotate + deduplicate command — compose via shell pipeline
- `MinHashLSHEnsemble` containment queries — deferred for `--ref` enhancement

---

## Proposed Solution

### Architecture notes (scalability)

v1 loads all records into memory for Union-Find. Memory budget at 100K files: ~25 fields × 100K ≈ manageable; MinHash signatures (128 × 4 bytes × 100K) ≈ 50MB. Beyond ~500K files, a streaming multi-pass architecture is required:

- pass 1: streaming exact hash (O(1) memory per record)
- pass 2: generate MinHash signatures → write to temp file
- pass 3: LSH / pairs / Union-Find on signatures only
- pass 4: streaming output join

This is deferred to a follow-up CHG. v1 documents the limit explicitly.

### Input / output contract

#### Input modes

| Mode | Trigger | Source text | `score` available? |
|---|---|---|---|
| Raw directory | `input_path` is a directory | `.py` files read via `tokenize.open()` | No — `best_score` invalid |
| Annotated JSONL | `input_path` is `.jsonl` with `score` field | `content` field if present; else `path` on disk | Yes |
| Unannotated manifest | `input_path` is `.jsonl` without `score` | `content` field if present; else `path` on disk | No — `best_score` invalid |

**JSONL field contract:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `path` | `str` | Always | Relative (to manifest dir) or absolute |
| `score` | `float` | Only for `--keep best_score` | 0.0–100.0; from `dataset_annotator.py` |
| `content` | `str` | Optional | Inline Python source; used instead of reading `path` from disk if present |
| `content_sha256` | `str` | Optional | SHA-256 of normalised source; if present, validated against disk read |
| All other fields | any | Optional | Preserved verbatim in output |

**Reproducibility contract:** `_read_source(record)` is the single entry point for obtaining source text. Priority: (1) `content` field inline → use directly, never touch disk; (2) else read from `path` via `tokenize.open()`. In both cases, normalise the source (`\r\n→\n`, strip trailing whitespace per line), compute `sha256(normalised)`, and return `(source_str, computed_sha256)`. If the record has a pre-existing `content_sha256`, validate against the computed value; mismatch → `dedup_error_type="content_mismatch"`. All subsequent operations (hashing, tokenisation, shingle generation) work on the in-memory source string returned by `_read_source()` — they never re-open the file. This makes JSONL with inline `content` fields fully self-contained and portable.

**`best_score` validation and label-bias warning:** Checked at the start of `deduplicate()`, after `_load_records()` reads the first record. Raw directory or scoreless manifest → `ValueError`. **Label-bias note:** `best_score` selects the highest-scoring representative from each near-dup cluster. Since near-dedup deliberately strips variable names, comments, and whitespace — which may legitimately affect quality scores — this strategy can systematically shift the dataset toward higher-score samples. Use only if this bias is intentional. Default strategy is `canonical_path`.

#### Output fields appended to every record

```json
{
  "content_sha256": "abcd1234...",
  "dedup_group_id": "abcd1234ef567890",
  "dedup_cluster_size": 3,
  "dedup_kept": true,
  "dedup_reason": "near",
  "dedup_similarity_max": 0.87,
  "dedup_error_type": null,
  "dedup_error": null
}
```

| Field | Type | Values | Notes |
|---|---|---|---|
| `content_sha256` | `str\|null` | hex or null | SHA-256 of **normalised** source (line-ending + trailing-whitespace normalised, not raw bytes); `null` only when source could not be obtained at all (io_error, decode_error). For content_mismatch: emits the **current** computed hash (source was read successfully) |
| `dedup_group_id` | `str\|null` | 16-char hex | `sha256(sorted(member_content_sha256s))[:16]`; `null` for unique files |
| `dedup_cluster_size` | `int` | ≥1 | 1 = unique file |
| `dedup_kept` | `bool` | — | `true` = in output; `false` = removed duplicate |
| `dedup_reason` | `str` | `unique\|exact\|near\|ref_exact\|ref_near\|error` | Why this record's kept/removed status was assigned |
| `dedup_similarity_max` | `float\|null` | 0–1 | Max verified Jaccard with any cluster member; `null` for exact/unique |
| `dedup_error_type` | `str\|null` | see below | `null` when no error; one of `io_error`, `decode_error`, `content_mismatch` on failure |
| `dedup_error` | `str\|null` | — | Human-readable error message; `null` when no error |

**`dedup_group_id` stability:** Based on sorted member `content_sha256` values, not on the representative's hash. This means `dedup_group_id` is invariant to keep strategy changes.

By default only kept records are written. `--keep-removed` writes all records with `dedup_kept=false` for auditing.

### Module structure

```python
DatasetDeduplicator
  __init__(threshold=0.8, keep="canonical_path", mode="both", workers=1)
    # Validates at construction: threshold in (0, 1], keep in {"canonical_path", "best_score"},
    #   mode in {"exact", "both"}
    # If mode=="both" and datasketch not installed → ImportError
    # Note: best_score validation (requires score field) cannot happen here —
    #   __init__ has no input_path. Deferred to deduplicate() after _load_records().
  deduplicate(input_path, output_path, ref_path=None) -> DeduplicationReport
    # After _load_records(): if keep=="best_score" and first record has no score → ValueError
  deduplicate(input_path, output_path, ref_path=None) -> DeduplicationReport
  _load_records(input_path) -> list[dict]
  _read_source(record) -> tuple[str, str] | None
    # returns (source_str, content_sha256) on success; None on io_error/decode_error
    # content_mismatch: returns the tuple (source was read) but sets record error fields
  _exact_hash_pass(records) -> tuple[list[dict], dict[str, list[dict]]]
    # returns (representatives: list[dict], exact_cluster_map: {sha256: [all members]})
  _minhash_lsh_pass(records) -> list[list[dict]]
  _verify_jaccard(shingles_a, shingles_b) -> float
  _union_find(pairs) -> list[list[dict]]
  _expand_with_exact_members(near_clusters, exact_cluster_map) -> list[list[dict]]
  _select_representative(cluster, keep) -> dict
```

`DeduplicationReport` dataclass:

```python
@dataclass
class DeduplicationReport:
    total_input: int              # records successfully parsed from input (excludes malformed/skipped JSONL lines)
    total_output: int             # records written with dedup_kept=true
    exact_duplicates_removed: int
    near_duplicates_removed: int
    ref_duplicates_removed: int       # 0 if --ref not used
    cluster_count: int
    dedup_rate: float                 # (total_input - total_output) / total_input
```

### Algorithm pipeline (ordered)

```
Input records
  │
  ├─ [1] Exact hash pass
  │    - Call _read_source(record) → (source_str, content_sha256)
  │      (handles content field priority, disk read, normalisation, hash validation)
  │    - Error records (io_error, decode_error): content_sha256=null; set aside, not grouped
  │    - content_mismatch: content_sha256 = CURRENT computed hash; set aside with
  │      dedup_reason="error", dedup_kept=true — does NOT participate in grouping
  │    - All error records pass through to output untouched (no dedup applied)
  │    - Remaining (non-error) records: group by SHA-256 → exact duplicate clusters
  │    - Keep one representative per cluster (tie-break: see §Tie-break rules)
  │    - Store exact_cluster_map: {sha256: [all members incl. representative]}
  │    - Pass only representatives to step 2; record exact_duplicates_removed
  │
  ├─ [2] MinHash signature computation (representatives only)
  │    - Tokenise the in-memory source_str (via tokenize on StringIO; encoding already resolved)
  │    - Normalise tokens: keywords kept, other NAME → ID, STRING → STR, NUMBER → NUM
  │    - Discard: COMMENT, NEWLINE, NL, INDENT, DEDENT, ENCODING tokens
  │    - Build token 5-grams (shingles)
  │    - Files with < 5 tokens: skip MinHash (exact_only policy); still included in output
  │    - Compute 128-permutation MinHash signature
  │    - LSH parameters: datasketch.MinHashLSH(threshold=threshold, num_perm=128)
  │      ← bands/rows auto-computed by datasketch; NOT hardcoded
  │
  ├─ [3] Candidate pair generation + Jaccard verification
  │    - LSH query → candidate pairs (approximate; may have false positives)
  │    - For each candidate pair (a, b): compute actual Jaccard(shingles_a, shingles_b)
  │    - Accept pair only if verified Jaccard ≥ threshold
  │
  ├─ [4] Union-Find clustering (representatives only)
  │    - Build connected components from accepted pairs
  │    - Each component = one near-duplicate cluster of representatives
  │
  ├─ [5] Exact cluster re-expansion
  │    - For each near-dup cluster of representatives, expand using exact_cluster_map
  │    - Example: if {A,C} are near-dup representatives, and A had exact dup B,
  │      final cluster = {A, B, C} with dedup_group_id based on all 3 members
  │    - dedup_group_id = sha256(sorted(member content_sha256 values))[:16]
  │
  ├─ [6] Representative selection
  │    - canonical_path: lexicographically smallest path (stable sort; see Tie-break rules)
  │    - best_score: highest score (tie-break by path asc, then original index asc)
  │    - Assign dedup_group_id, dedup_cluster_size, dedup_kept, dedup_reason,
  │      dedup_similarity_max to all cluster members
  │    - Update near_duplicates_removed counter
  │
  └─ [7] Reference-set filtering (--ref only)
       Separate mechanism from steps 1–6:
       a) Exact ref check: compute content_sha256 of each ref record; check all kept
          records (not just representatives) for matches → dedup_reason="ref_exact"
       b) Near ref check: build reference-only MinHashLSH index from ref records;
          query all kept records; verify Jaccard ≥ threshold;
          matched records → dedup_reason="ref_near"
       c) Representative backfill: when a cluster's representative is removed by ref,
          re-select from the remaining non-ref-matched members of the same cluster
          using the same keep strategy + tie-break rules. Only drop the entire cluster
          (all members get dedup_reason="ref_exact"|"ref_near") when ALL members
          match ref records.
       Default match policy: direct verified pair only (not component propagation)
       Future: --ref-match-policy component for transitive ref removal
       Update ref_duplicates_removed counter
```

### Tie-break rules (all strategies)

When multiple records are equivalent under the primary keep key:
1. Primary key (score desc for `best_score`, path asc for `canonical_path`)
2. `path` asc
3. Original record index asc (position in input file)

Applied consistently for deterministic output across runs.

### Tokenisation

| Token type | Normalisation |
|---|---|
| Python keywords | kept as-is |
| Other `NAME` tokens | → `ID` |
| `STRING` | → `STR` |
| `NUMBER` | → `NUM` |
| `COMMENT`, `NEWLINE`, `NL`, `INDENT`, `DEDENT`, `ENCODING` | discarded |

Source is read via `tokenize.open()` which detects encoding from BOM or PEP 263 cookie (`# -*- coding: X -*-`). This handles all valid Python source files, not just UTF-8.

**Normalized exact hash trade-off:** The "exact" hash pass normalises line endings (`\r\n→\n`) and strips trailing whitespace per line before hashing. This is not raw-bytes exact: in rare cases, trailing whitespace inside multi-line strings is semantically significant and would be normalised away, producing a false-positive exact match. This is an accepted trade-off — the alternative (raw-bytes hash) would miss cross-platform line-ending variants, which are far more common than semantically significant trailing whitespace in Python string literals.

### Failure contract

| Failure mode | Behaviour |
|---|---|
| `datasketch` not installed, `mode == "both"` | `ImportError` at `__init__()` |
| `--keep best_score` on scoreless input | `ValueError` at `deduplicate()` after `_load_records()` (not at `__init__` — no input path available at construction) |
| `threshold` outside `(0, 1]` | `ValueError` at `__init__()` |
| Malformed JSONL line | Skip; warning to stderr; continue |
| `path` field missing | Skip; warning to stderr; continue |
| File not found / unreadable (OS error) | `dedup_error_type="io_error"`, `dedup_kept=true`, `dedup_reason="error"` |
| `content_sha256` mismatch (file changed after annotation) | `dedup_error_type="content_mismatch"`, `dedup_kept=true`, `dedup_reason="error"` |
| Encoding detection failure (`tokenize.open()` fails) | `dedup_error_type="decode_error"`, `dedup_kept=true`, `dedup_reason="error"`; skipped from both hash and MinHash passes |
| `tokenize` failure on successfully opened file | Skipped from MinHash (exact_only policy); warning to stderr; included in output |
| File too short for 5-grams (< 5 tokens) | Exact-only policy: included in exact pass, skipped from MinHash |
| I/O error writing output | Exception propagates; write to temp file then atomic rename to final path |

The pipeline does not abort on per-record errors. Startup failures abort before any processing.

**Namespace:** All dedup-specific error/provenance fields use `dedup_` prefix (`dedup_error`, `dedup_error_type`, `dedup_group_id`, etc.) to avoid collision with upstream fields.

### CLI

```bash
# Deduplicate an annotated JSONL
python dataset_dedup.py annotated.jsonl -o annotated_deduped.jsonl

# Deduplicate a raw directory
python dataset_dedup.py /data/bugsinpy/ -o deduped.jsonl

# Exact hash only
python dataset_dedup.py annotated.jsonl -o out.jsonl --mode exact

# Custom threshold (calibrate on your dataset; 0.8 is conservative)
python dataset_dedup.py annotated.jsonl -o out.jsonl --threshold 0.7

# Keep best-quality representative (label-biased; opt-in only)
python dataset_dedup.py annotated.jsonl -o out.jsonl --keep best_score

# Cross-split deduplication (remove training items similar to test set)
python dataset_dedup.py train.jsonl -o train_clean.jsonl --ref test.jsonl

# Dry run
python dataset_dedup.py annotated.jsonl --dry-run

# Parallel MinHash computation
python dataset_dedup.py annotated.jsonl -o out.jsonl --workers 8

# Audit removed records
python dataset_dedup.py annotated.jsonl -o out.jsonl --keep-removed
```

### Typical pipeline usage

```bash
# Step 1: Annotate (content_sha256 not yet emitted by annotator; dedup computes it from disk)
python dataset_annotator.py /data/bugsinpy/ -o annotated.jsonl --source BugsInPy --license MIT

# Step 2: Deduplicate within training set
python dataset_dedup.py annotated.jsonl -o train_deduped.jsonl

# Step 3: Remove training items that leak into test set
python dataset_dedup.py train_deduped.jsonl -o train_clean.jsonl --ref test.jsonl
```

### Dependencies

| Package | Source | Use |
|---|---|---|
| `datasketch` | PyPI (MIT) | MinHash + LSH (auto band/row selection) |
| `tokenize` | Python stdlib | Encoding-aware source reading and token normalisation |
| `hashlib` | Python stdlib | SHA-256 hashing |

### Impact

- **New file:** `dataset_dedup.py`
- **New tests:** `tests/test_dataset_dedup.py` (exact hash, MinHash, Jaccard verification, Union-Find, exact cluster re-expansion, cross-split ref dedup, `canonical_path`/`best_score` keep strategies, label-bias ValueError on scoreless input, `content_sha256` validation, `dedup_group_id` stability, all failure modes, DeduplicationReport counters, tie-break determinism)
- **Annotator contract (pending):** `dataset_annotator.py` does not yet emit `content_sha256`. A follow-up CHG must add it to HUA-2109-PRP Tier 1 schema before annotated JSONL → dedup pipeline can benefit from content validation. Without it, `dataset_dedup.py` still works (computes `content_sha256` itself from disk reads) but loses the mismatch-detection safety net
- **New optional dependency:** `datasketch` — install with `pip install datasketch`; document in CLAUDE.md
- **Makefile:** add `dataset_dedup.py` to both `lint` (line 9) and `fmt` (line 12); add `tests/test_dataset_dedup.py` to same targets
- **CLAUDE.md:** add `datasketch` to Required Tools and usage note

---

## Open Questions

_All open questions resolved before review._

1. **Why `datasketch` LSH auto-computes bands/rows?**
   `datasketch.MinHashLSH(threshold=t, num_perm=128)` internally optimises bands/rows for the given threshold to maximise recall at that threshold. Hardcoding `32×4` would create a mismatch: the candidate generation recall is calibrated for a specific threshold, but the CLI allows any threshold — producing unpredictable false-negative rates at non-default thresholds.

2. **Why `canonical_path` not `first`?**
   "First" implies input-order dependence (non-deterministic across platforms). `canonical_path` (lexicographically smallest path) is deterministic, stable under shuffle, and clearly named.

3. **Why is 0.8 the default threshold?**
   It is a **conservative default**, not a literature standard. The Stack v2 uses 0.7; BigCode experiments show lower thresholds further improve downstream performance. Users should calibrate on their specific dataset. The default 0.8 minimises false positives at the cost of recall; for ML training data quality, false negatives (keeping near-dups) are typically more costly than false positives (removing non-dups), so calibrating toward 0.7 is often better.

4. **Why does `--ref` use a separate mechanism?**
   Standard Union-Find on `(input ∪ ref)` is dangerous: if A~B and B~C (but A≁C), Union-Find puts all three in one component. When B is a ref record, C would be removed even though C≁B below threshold. The separate mechanism (ref-only LSH index + direct verified pair matching) ensures only records with a direct verified match against a ref record are removed. Transitive removal is opt-in via `--ref-match-policy component`.

5. **Why is `dedup_group_id` based on sorted member hashes?**
   A representative-based ID changes when the keep strategy changes (`canonical_path` vs `best_score` may pick different representatives from the same cluster). A member-hash-based ID is invariant to keep strategy, enabling stable cluster tracking across runs and parameter sweeps.

6. **Should dedup run before or after annotation?**
   Both orders are valid. Dedup-before-annotate saves compute (skip annotation of removed files). Annotate-before-dedup enables `--keep best_score` and `content_sha256` validation. For ≤10K files: annotate first. For 10K–100K files: either is fine. Above 100K: dedup first (annotation compute dominates).

---

## Review

- [x] Reviewer 1 (Codex): 9.8 / 10 — APPROVED (v3, 2026-03-22)
- [x] Reviewer 2 (Gemini): 9.9 / 10 — APPROVED (v1, 2026-03-22)
- [x] Approved on: 2026-03-22
- [x] External review round 1 (v4): 12 issues incorporated
- [x] External review round 2 (v5): 5 pre-implementation edits; rated 9.3/10
- [x] External review round 3 (v6): 4 schema/doc consistency fixes; rated 9.0/10
- [x] External review round 4 (v7): 3 API/doc consistency fixes; rated 9.4/10 — cleared for implementation

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | v7: External review round 4 (9.4/10) — best_score validation moved from __init__ to deduplicate() (no input_path at construction); content_mismatch records explicitly excluded from grouping (set aside as error, not grouped into clusters); _read_source return type fixed to tuple|None; _exact_hash_pass first return type fixed to list[dict] | Claude Code |
| 2026-03-22 | v6: External review round 3 (9.0/10) — content_sha256 keeps computed hash on content_mismatch (null only for io/decode_error); dedup_error/dedup_error_type added to output schema table; pipeline usage comment fixed (annotator pending); exact hash renamed to normalized exact with trade-off note; DeduplicationReport.total_input defined as post-skip count | Claude Code |
| 2026-03-22 | v5: External review round 2 — content_sha256 nullable for error records; removed mode="minhash" (only exact/both); --ref representative backfill on removal; _read_source() as single source entry point (no disk re-reads); HUA-2109 dependency state clarified as pending | Claude Code |
| 2026-03-22 | v4: Incorporated external review — reproducibility contract (content_sha256 validation, content field priority); scope capped at ≤100K local; LSH params auto-computed from threshold; exact cluster re-expansion step; --ref separate exact/near mechanism; best_score label-bias warning; canonical_path rename; dedup_group_id 16-char member-hash-based; dedup_ namespace for error fields; tokenize.open() for encoding; exact_only policy for short files; tie-break rules; expanded output schema (dedup_cluster_size, dedup_reason, dedup_similarity_max); threshold calibration note | Claude Code |
| 2026-03-22 | v3: Formalised JSONL field contract table; split tokenize failure from UTF-8 decode failure | Claude Code |
| 2026-03-22 | v2: Added input/output contract (3 modes, path resolution, best_score validation); explicit algorithm pipeline (6 steps with Union-Find); failure contract table; fixed impact section | Claude Code |
| 2026-03-22 | v1: Initial version | Claude Code |
