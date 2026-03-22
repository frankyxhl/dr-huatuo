"""Dataset Deduplication Pipeline for huatuo.

Identifies and removes near-duplicate Python files from code datasets using
normalised exact hash + token-level MinHash/LSH with verified Jaccard + Union-Find.

Usage:
    python dataset_dedup.py <input_path> -o <output.jsonl> [options]

See HUA-2113-PRP for full specification.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import keyword
import os
import sys
import tempfile
import tokenize
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DeduplicationReport:
    """Summary statistics from a deduplication run."""

    total_input: int = 0
    total_output: int = 0
    exact_duplicates_removed: int = 0
    near_duplicates_removed: int = 0
    ref_duplicates_removed: int = 0
    cluster_count: int = 0
    dedup_rate: float = 0.0


# ---------------------------------------------------------------------------
# Tokenisation helpers (module-level for pickling in multiprocessing)
# ---------------------------------------------------------------------------

_DISCARD_TYPES = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
    }
)

_PYTHON_KEYWORDS = frozenset(keyword.kwlist)


def _normalise_source(source: str) -> str:
    """Normalise line endings and strip trailing whitespace per line."""
    lines = source.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def _hash_source(normalised: str) -> str:
    """SHA-256 of normalised source string."""
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _tokenise_and_normalise(source: str, path: str = "<unknown>") -> list[str]:
    """Tokenise Python source and normalise tokens per PRP spec.

    Returns a list of normalised token strings.
    Keywords kept as-is, other NAME -> ID, STRING -> STR, NUMBER -> NUM.
    COMMENT, NEWLINE, NL, INDENT, DEDENT, ENCODING discarded.

    Args:
        source: Python source text.
        path: File path for error reporting (used in stderr warning).
    """
    tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in _DISCARD_TYPES:
                continue
            if tok.type == tokenize.ENDMARKER:
                continue
            if tok.type == tokenize.NAME:
                if tok.string in _PYTHON_KEYWORDS:
                    tokens.append(tok.string)
                else:
                    tokens.append("ID")
            elif tok.type == tokenize.STRING:
                tokens.append("STR")
            elif tok.type == tokenize.NUMBER:
                tokens.append("NUM")
            else:
                tokens.append(tok.string)
    except tokenize.TokenError as e:
        print(f"Warning: tokenize failed for {path}: {e}", file=sys.stderr)
    return tokens


def _build_shingles(tokens: list[str], n: int = 5) -> set[tuple[str, ...]]:
    """Build n-gram shingles from token list."""
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _compute_minhash_for_record(args: tuple) -> tuple[int, object, set] | None:
    """Compute MinHash signature for a single record. Used in parallel."""
    from datasketch import MinHash

    idx, source, num_perm = args
    tokens = _tokenise_and_normalise(source)
    shingles = _build_shingles(tokens)
    if not shingles:
        return None
    mh = MinHash(num_perm=num_perm)
    for s in shingles:
        mh.update(" ".join(s).encode("utf-8"))
    return (idx, mh, shingles)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class DatasetDeduplicator:
    """Deduplicates Python code datasets via exact hash + MinHash/LSH."""

    NUM_PERM = 128

    def __init__(
        self,
        threshold: float = 0.8,
        keep: str = "canonical_path",
        mode: str = "both",
        workers: int = 1,
    ) -> None:
        if threshold <= 0 or threshold > 1:
            raise ValueError(f"threshold must be in (0, 1], got {threshold}")
        if keep not in ("canonical_path", "best_score"):
            raise ValueError(
                f"keep must be 'canonical_path' or 'best_score', got {keep!r}"
            )
        if mode not in ("exact", "both"):
            raise ValueError(f"mode must be 'exact' or 'both', got {mode!r}")
        if mode == "both":
            try:
                import datasketch  # noqa: F401
            except ImportError:
                raise ImportError(
                    "datasketch is required for mode='both'. "
                    "Install with: pip install datasketch"
                )
        self.threshold = threshold
        self.keep = keep
        self.mode = mode
        self.workers = workers

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def deduplicate(
        self,
        input_path: str,
        output_path: str | None = None,
        ref_path: str | None = None,
        dry_run: bool = False,
        keep_removed: bool = False,
    ) -> DeduplicationReport:
        """Run the full deduplication pipeline.

        Args:
            input_path: Path to directory of .py files or JSONL file.
            output_path: Path for output JSONL. Required unless dry_run.
            ref_path: Optional reference JSONL for cross-split dedup.
            dry_run: If True, compute stats but do not write output.
            keep_removed: If True, include removed records in output.

        Returns:
            DeduplicationReport with summary statistics.
        """
        records = self._load_records(input_path)

        # Validate best_score strategy
        if self.keep == "best_score":
            if not records or "score" not in records[0]:
                raise ValueError(
                    "keep='best_score' requires records with a 'score' field. "
                    "Raw directories and scoreless JSONL do not have scores."
                )

        report = DeduplicationReport(total_input=len(records))

        # Step 1: Read source and compute hashes for all records
        error_records = []
        good_records = []
        for r in records:
            result = self._read_source(r)
            if result is None:
                # io_error or decode_error
                self._set_error_output(r)
                error_records.append(r)
            elif r.get("dedup_error_type") == "content_mismatch":
                # content_mismatch: set aside, not grouped
                self._set_error_output(r)
                error_records.append(r)
            else:
                good_records.append(r)

        # Step 2: Exact hash pass
        reps, exact_cluster_map = self._exact_hash_pass(good_records)
        exact_removed = len(good_records) - len(reps)
        report.exact_duplicates_removed = exact_removed

        # Step 3-5: MinHash/LSH pass (on representatives only)
        near_clusters: list[list[dict]] = []
        if self.mode == "both" and len(reps) > 1:
            near_clusters = self._minhash_lsh_pass(reps)

        # Step 5: Exact cluster re-expansion
        if near_clusters:
            near_clusters = self._expand_with_exact_members(
                near_clusters, exact_cluster_map
            )

        # Collect all records in near-dup clusters
        near_cluster_ids = set()
        for cluster in near_clusters:
            for r in cluster:
                near_cluster_ids.add(id(r))

        # Step 6: Representative selection and output annotation
        all_output_records = []

        # Process near-dup clusters
        near_removed = 0
        for cluster in near_clusters:
            rep = self._select_representative(cluster, self.keep)
            group_id = self._compute_group_id(cluster)
            max_sim = self._compute_max_similarity(cluster)
            for r in cluster:
                is_kept = r is rep
                r["dedup_group_id"] = group_id
                r["dedup_cluster_size"] = len(cluster)
                r["dedup_kept"] = is_kept
                r["dedup_reason"] = "near" if not is_kept else "near"
                # Representative of a near cluster: reason is still "near"
                # (it survived near-dup selection)
                r["dedup_similarity_max"] = max_sim
                r["dedup_error_type"] = r.get("dedup_error_type")
                r["dedup_error"] = r.get("dedup_error")
                if not is_kept:
                    near_removed += 1
                all_output_records.append(r)

        report.near_duplicates_removed = near_removed
        report.cluster_count = len(near_clusters)

        # Process exact-only clusters (those whose reps are NOT in near clusters)
        for sha, members in exact_cluster_map.items():
            rep_of_exact = members[0]  # first is the representative from exact pass
            if id(rep_of_exact) in near_cluster_ids:
                continue  # already handled in near-dup expansion
            if len(members) == 1:
                # Unique file
                r = members[0]
                r["dedup_group_id"] = None
                r["dedup_cluster_size"] = 1
                r["dedup_kept"] = True
                r["dedup_reason"] = "unique"
                r["dedup_similarity_max"] = None
                r["dedup_error_type"] = r.get("dedup_error_type")
                r["dedup_error"] = r.get("dedup_error")
                all_output_records.append(r)
            else:
                # Exact-only cluster (no near-dup partner)
                group_id = self._compute_group_id(members)
                rep = self._select_representative(members, self.keep)
                for r in members:
                    is_kept = r is rep
                    r["dedup_group_id"] = group_id
                    r["dedup_cluster_size"] = len(members)
                    r["dedup_kept"] = is_kept
                    r["dedup_reason"] = "exact"
                    r["dedup_similarity_max"] = None
                    r["dedup_error_type"] = r.get("dedup_error_type")
                    r["dedup_error"] = r.get("dedup_error")
                    all_output_records.append(r)
                report.cluster_count += 1

        # Add error records to output
        all_output_records.extend(error_records)

        # Step 7: Reference-set filtering
        if ref_path is not None:
            ref_removed = self._ref_dedup(all_output_records, ref_path)
            report.ref_duplicates_removed = ref_removed

        # Compute output counts
        kept_records = [r for r in all_output_records if r.get("dedup_kept", False)]
        report.total_output = len(kept_records)
        if report.total_input > 0:
            report.dedup_rate = (
                report.total_input - report.total_output
            ) / report.total_input

        # Write output
        if not dry_run and output_path is not None:
            records_to_write = all_output_records if keep_removed else kept_records
            self._write_output(records_to_write, output_path)

        return report

    # -------------------------------------------------------------------
    # Loading
    # -------------------------------------------------------------------

    def _load_records(self, input_path: str) -> list[dict]:
        """Load records from directory or JSONL file."""
        p = Path(input_path)
        if p.is_dir():
            return self._load_from_directory(p)
        elif p.suffix == ".jsonl" or p.name.endswith(".jsonl"):
            return self._load_from_jsonl(p)
        else:
            # Try as JSONL
            return self._load_from_jsonl(p)

    def _load_from_directory(self, directory: Path) -> list[dict]:
        """Load .py files from a directory as records."""
        records = []
        py_files = sorted(directory.rglob("*.py"))
        for idx, py_file in enumerate(py_files):
            records.append({"path": str(py_file), "_idx": idx})
        return records

    def _load_from_jsonl(self, jsonl_path: Path) -> list[dict]:
        """Load records from JSONL file."""
        records = []
        idx = 0
        with open(jsonl_path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    print(
                        f"Warning: Malformed JSONL at line {line_num}, skipping",
                        file=sys.stderr,
                    )
                    continue
                if "path" not in record:
                    print(
                        f"Warning: Missing 'path' at line {line_num}, skipping",
                        file=sys.stderr,
                    )
                    continue
                record["_idx"] = idx
                idx += 1
                records.append(record)
        return records

    # -------------------------------------------------------------------
    # Source reading
    # -------------------------------------------------------------------

    def _read_source(self, record: dict) -> tuple[str, str] | None:
        """Read and normalise source text for a record.

        Returns (normalised_source, content_sha256) on success, None on error.
        Sets error fields on the record for io_error, decode_error, content_mismatch.
        """
        source = None

        # Priority 1: content field
        if "content" in record and record["content"] is not None:
            source = record["content"]
        else:
            # Priority 2: read from path
            path = record.get("path", "")
            try:
                with tokenize.open(path) as f:
                    source = f.read()
            except (OSError, FileNotFoundError) as e:
                record["dedup_error_type"] = "io_error"
                record["dedup_error"] = str(e)
                record["content_sha256"] = None
                return None
            except (SyntaxError, UnicodeDecodeError) as e:
                record["dedup_error_type"] = "decode_error"
                record["dedup_error"] = str(e)
                record["content_sha256"] = None
                return None

        normalised = _normalise_source(source)
        computed_sha = _hash_source(normalised)
        record["_source"] = normalised

        # Validate pre-existing content_sha256 if present
        if "content_sha256" in record and record["content_sha256"] is not None:
            if record["content_sha256"] != computed_sha:
                record["dedup_error_type"] = "content_mismatch"
                record["dedup_error"] = (
                    f"content_sha256 mismatch: expected {record['content_sha256']}, "
                    f"got {computed_sha}"
                )
                record["content_sha256"] = computed_sha
                return (normalised, computed_sha)

        record["content_sha256"] = computed_sha
        return (normalised, computed_sha)

    # -------------------------------------------------------------------
    # Exact hash pass
    # -------------------------------------------------------------------

    def _exact_hash_pass(
        self, records: list[dict]
    ) -> tuple[list[dict], dict[str, list[dict]]]:
        """Group records by normalised content SHA-256.

        Returns:
            (representatives, exact_cluster_map) where exact_cluster_map maps
            sha256 -> [all members including representative].
            Representative is selected by tie-break rules (path asc, idx asc).
        """
        clusters: dict[str, list[dict]] = {}
        for r in records:
            sha = r["content_sha256"]
            if sha not in clusters:
                clusters[sha] = []
            clusters[sha].append(r)

        representatives = []
        for sha, members in clusters.items():
            # Sort by path asc, then idx asc for deterministic selection
            members.sort(key=lambda r: (r["path"], r.get("_idx", 0)))
            representatives.append(members[0])

        return representatives, clusters

    # -------------------------------------------------------------------
    # MinHash/LSH pass
    # -------------------------------------------------------------------

    def _minhash_lsh_pass(self, records: list[dict]) -> list[list[dict]]:
        """Compute MinHash signatures, run LSH, verify Jaccard, cluster via Union-Find.

        Args:
            records: List of representative records (one per exact-hash group).

        Returns:
            List of near-duplicate clusters (each cluster has >= 2 records).
        """
        from datasketch import MinHash, MinHashLSH

        # Compute signatures
        idx_to_record = {r.get("_idx", i): r for i, r in enumerate(records)}
        signatures: dict[int, MinHash] = {}
        shingles_map: dict[int, set] = {}

        if self.workers > 1:
            args_list = []
            for i, r in enumerate(records):
                source = r.get("_source", "")
                idx = r.get("_idx", i)
                args_list.append((idx, source, self.NUM_PERM))
            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                for result in executor.map(_compute_minhash_for_record, args_list):
                    if result is not None:
                        idx, mh, shingles = result
                        signatures[idx] = mh
                        shingles_map[idx] = shingles
        else:
            for i, r in enumerate(records):
                source = r.get("_source", "")
                idx = r.get("_idx", i)
                tokens = _tokenise_and_normalise(source, r.get("path", "<unknown>"))
                shingles = _build_shingles(tokens)
                if not shingles:
                    continue
                mh = MinHash(num_perm=self.NUM_PERM)
                for s in shingles:
                    mh.update(" ".join(s).encode("utf-8"))
                signatures[idx] = mh
                shingles_map[idx] = shingles

        if not signatures:
            return []

        # Build LSH index
        lsh = MinHashLSH(threshold=self.threshold, num_perm=self.NUM_PERM)
        for idx, mh in signatures.items():
            try:
                lsh.insert(str(idx), mh)
            except ValueError:
                # Duplicate key
                pass

        # Generate candidate pairs and verify Jaccard
        verified_pairs = []
        # Map from (obj_id_a, obj_id_b) -> jaccard score (canonical key: min,max)
        pair_jaccard: dict[tuple[int, int], float] = {}
        seen_pairs = set()
        for idx, mh in signatures.items():
            candidates = lsh.query(mh)
            for cand_str in candidates:
                cand_idx = int(cand_str)
                if cand_idx == idx:
                    continue
                pair_key = (min(idx, cand_idx), max(idx, cand_idx))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                # Verify Jaccard
                jaccard = self._verify_jaccard(
                    shingles_map[idx], shingles_map[cand_idx]
                )
                if jaccard >= self.threshold:
                    rec_a = idx_to_record[idx]
                    rec_b = idx_to_record[cand_idx]
                    verified_pairs.append((rec_a, rec_b))
                    obj_key = (min(id(rec_a), id(rec_b)), max(id(rec_a), id(rec_b)))
                    pair_jaccard[obj_key] = jaccard

        # Union-Find clustering
        clusters = self._union_find(verified_pairs)

        # Annotate each cluster with the max observed Jaccard
        for cluster in clusters:
            max_j = 0.0
            for i, ra in enumerate(cluster):
                for rb in cluster[i + 1 :]:
                    obj_key = (min(id(ra), id(rb)), max(id(ra), id(rb)))
                    j = pair_jaccard.get(obj_key, 0.0)
                    if j > max_j:
                        max_j = j
            for rec in cluster:
                rec["_near_max_jaccard"] = max_j

        return clusters

    # -------------------------------------------------------------------
    # Jaccard verification
    # -------------------------------------------------------------------

    def _verify_jaccard(self, shingles_a: set, shingles_b: set) -> float:
        """Compute exact Jaccard similarity between two shingle sets."""
        if not shingles_a and not shingles_b:
            return 1.0
        if not shingles_a or not shingles_b:
            return 0.0
        intersection = len(shingles_a & shingles_b)
        union = len(shingles_a | shingles_b)
        return intersection / union if union > 0 else 0.0

    # -------------------------------------------------------------------
    # Union-Find
    # -------------------------------------------------------------------

    def _union_find(self, pairs: list[tuple[dict, dict]]) -> list[list[dict]]:
        """Build connected components from verified pairs using Union-Find.

        Returns list of clusters, each with >= 2 records.
        """
        if not pairs:
            return []

        parent: dict[int, int] = {}

        def find(x: int) -> int:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Collect all records by id
        id_to_record: dict[int, dict] = {}
        for a, b in pairs:
            aid = id(a)
            bid = id(b)
            id_to_record[aid] = a
            id_to_record[bid] = b
            parent.setdefault(aid, aid)
            parent.setdefault(bid, bid)
            union(aid, bid)

        # Group by root
        components: dict[int, list[dict]] = {}
        for rid, record in id_to_record.items():
            root = find(rid)
            if root not in components:
                components[root] = []
            components[root].append(record)

        return [c for c in components.values() if len(c) >= 2]

    # -------------------------------------------------------------------
    # Exact cluster re-expansion
    # -------------------------------------------------------------------

    def _expand_with_exact_members(
        self,
        near_clusters: list[list[dict]],
        exact_cluster_map: dict[str, list[dict]],
    ) -> list[list[dict]]:
        """Expand near-dup clusters by adding exact duplicate members.

        For each representative in a near-dup cluster, add all its
        exact duplicates from the exact_cluster_map.
        """
        expanded = []
        for cluster in near_clusters:
            full_cluster = []
            seen_ids = set()
            for rep in cluster:
                sha = rep.get("content_sha256")
                if sha and sha in exact_cluster_map:
                    for member in exact_cluster_map[sha]:
                        mid = id(member)
                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            full_cluster.append(member)
                else:
                    mid = id(rep)
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        full_cluster.append(rep)
            expanded.append(full_cluster)
        return expanded

    # -------------------------------------------------------------------
    # Representative selection
    # -------------------------------------------------------------------

    def _select_representative(self, cluster: list[dict], keep: str) -> dict:
        """Select the representative record from a cluster.

        Args:
            cluster: List of records in the cluster.
            keep: Strategy - 'canonical_path' or 'best_score'.

        Returns:
            The selected representative record.
        """
        if keep == "best_score":
            # Sort: score desc, path asc, idx asc
            sorted_cluster = sorted(
                cluster,
                key=lambda r: (
                    -r.get("score", 0),
                    r.get("path", ""),
                    r.get("_idx", 0),
                ),
            )
        else:
            # canonical_path: sort by path asc, idx asc
            sorted_cluster = sorted(
                cluster,
                key=lambda r: (r.get("path", ""), r.get("_idx", 0)),
            )
        return sorted_cluster[0]

    # -------------------------------------------------------------------
    # Group ID computation
    # -------------------------------------------------------------------

    def _compute_group_id(self, cluster: list[dict]) -> str:
        """Compute dedup_group_id from sorted member content_sha256 values."""
        shas = sorted(r.get("content_sha256", "") for r in cluster)
        combined = "".join(shas)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]

    # -------------------------------------------------------------------
    # Max similarity computation
    # -------------------------------------------------------------------

    def _compute_max_similarity(self, cluster: list[dict]) -> float | None:
        """Compute max pairwise Jaccard similarity in a cluster.

        Returns the actual max Jaccard stored by _minhash_lsh_pass,
        or None if the cluster contains only exact duplicates.
        """
        if len(cluster) <= 1:
            return None
        # Check if all members have same hash (exact only)
        shas = {r.get("content_sha256") for r in cluster}
        if len(shas) == 1:
            return None
        # Use stored max Jaccard from _minhash_lsh_pass if available
        max_j = cluster[0].get("_near_max_jaccard")
        if max_j is not None:
            return max_j
        # Fallback: return threshold as conservative minimum
        return self.threshold

    # -------------------------------------------------------------------
    # Reference-set deduplication
    # -------------------------------------------------------------------

    def _ref_dedup(self, records: list[dict], ref_path: str) -> int:
        """Apply cross-split reference deduplication.

        Args:
            records: All output records (will be modified in place).
            ref_path: Path to reference JSONL.

        Returns:
            Number of records removed by ref matching.
        """
        ref_records = self._load_records(ref_path)
        ref_hashes: set[str] = set()
        ref_sources: dict[str, str] = {}  # sha -> normalised source

        for rr in ref_records:
            result = self._read_source(rr)
            if result is not None:
                source, sha = result
                ref_hashes.add(sha)
                ref_sources[sha] = source

        removed = 0
        kept_records = [r for r in records if r.get("dedup_kept", False)]

        # Track which records are removed by ref (for backfill)
        ref_removed_ids: set[int] = set()

        # a) Exact ref check
        for r in kept_records:
            sha = r.get("content_sha256")
            if sha and sha in ref_hashes:
                r["dedup_kept"] = False
                r["dedup_reason"] = "ref_exact"
                ref_removed_ids.add(id(r))
                removed += 1

        # b) Near ref check (only in 'both' mode)
        if self.mode == "both" and ref_sources:
            from datasketch import MinHash, MinHashLSH

            # Build ref LSH index
            ref_lsh = MinHashLSH(threshold=self.threshold, num_perm=self.NUM_PERM)
            ref_sigs: dict[str, MinHash] = {}
            ref_shingles_map: dict[str, set] = {}

            for sha, source in ref_sources.items():
                tokens = _tokenise_and_normalise(source)
                shingles = _build_shingles(tokens)
                if not shingles:
                    continue
                mh = MinHash(num_perm=self.NUM_PERM)
                for s in shingles:
                    mh.update(" ".join(s).encode("utf-8"))
                ref_sigs[sha] = mh
                ref_shingles_map[sha] = shingles
                try:
                    ref_lsh.insert(sha, mh)
                except ValueError:
                    pass

            # Query kept records against ref
            still_kept = [r for r in kept_records if id(r) not in ref_removed_ids]
            for r in still_kept:
                source = r.get("_source", "")
                if not source:
                    continue
                tokens = _tokenise_and_normalise(source, r.get("path", "<unknown>"))
                shingles = _build_shingles(tokens)
                if not shingles:
                    continue
                mh = MinHash(num_perm=self.NUM_PERM)
                for s in shingles:
                    mh.update(" ".join(s).encode("utf-8"))
                candidates = ref_lsh.query(mh)
                for cand_sha in candidates:
                    if cand_sha in ref_shingles_map:
                        jaccard = self._verify_jaccard(
                            shingles, ref_shingles_map[cand_sha]
                        )
                        if jaccard >= self.threshold:
                            r["dedup_kept"] = False
                            r["dedup_reason"] = "ref_near"
                            ref_removed_ids.add(id(r))
                            removed += 1
                            break

        # c) Representative backfill
        if ref_removed_ids:
            self._backfill_representatives(records, ref_removed_ids, ref_hashes)

        return removed

    def _backfill_representatives(
        self,
        records: list[dict],
        ref_removed_ids: set[int],
        ref_hashes: set[str],
    ) -> None:
        """Re-select representatives for clusters whose rep was removed by ref.

        Before promoting a backfill candidate, check its content_sha256 against
        the ref hash set. If it matches, skip it. Only drop the entire cluster
        if ALL members match ref.
        """
        # Group records by dedup_group_id
        groups: dict[str, list[dict]] = {}
        for r in records:
            gid = r.get("dedup_group_id")
            if gid is not None:
                if gid not in groups:
                    groups[gid] = []
                groups[gid].append(r)

        for gid, members in groups.items():
            # Check if any member is still kept
            still_kept = [r for r in members if r.get("dedup_kept", False)]
            non_ref_removed = [r for r in members if id(r) not in ref_removed_ids]

            if not still_kept and non_ref_removed:
                # All kept members were removed by ref; backfill from non-ref
                # Find members that were removed by dedup (not ref)
                dedup_removed = [
                    r
                    for r in non_ref_removed
                    if not r.get("dedup_kept", False)
                    and r.get("dedup_reason") in ("exact", "near")
                ]
                if dedup_removed:
                    # Sort candidates by selection strategy for deterministic order
                    sorted_candidates = sorted(
                        dedup_removed,
                        key=lambda r: (r.get("path", ""), r.get("_idx", 0)),
                    )
                    if self.keep == "best_score":
                        sorted_candidates = sorted(
                            dedup_removed,
                            key=lambda r: (
                                -r.get("score", 0),
                                r.get("path", ""),
                                r.get("_idx", 0),
                            ),
                        )
                    # Promote first candidate whose sha is NOT in ref_hashes
                    for candidate in sorted_candidates:
                        sha = candidate.get("content_sha256")
                        if sha and sha in ref_hashes:
                            # This candidate matches ref; skip it
                            continue
                        candidate["dedup_kept"] = True
                        break
                    # If all candidates match ref, the entire cluster is dropped

    # -------------------------------------------------------------------
    # Error output helpers
    # -------------------------------------------------------------------

    def _set_error_output(self, record: dict) -> None:
        """Set default dedup output fields for error records."""
        record.setdefault("dedup_group_id", None)
        record.setdefault("dedup_cluster_size", 1)
        record["dedup_kept"] = True
        record["dedup_reason"] = "error"
        record.setdefault("dedup_similarity_max", None)
        # content_sha256 already set by _read_source

    # -------------------------------------------------------------------
    # Output writing
    # -------------------------------------------------------------------

    def _write_output(self, records: list[dict], output_path: str) -> None:
        """Write records to JSONL, using atomic temp file + rename."""
        # Remove internal fields before writing
        output_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(output_dir, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                for r in records:
                    # Remove internal fields
                    clean = {k: v for k, v in r.items() if not k.startswith("_")}
                    f.write(json.dumps(clean) + "\n")
            os.replace(tmp_path, output_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Deduplicate Python code datasets")
    parser.add_argument(
        "input_path",
        help="Path to directory of .py files or JSONL file",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output JSONL path (required unless --dry-run)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Jaccard similarity threshold (default: 0.8)",
    )
    parser.add_argument(
        "--keep",
        choices=["canonical_path", "best_score"],
        default="canonical_path",
        help="Keep strategy (default: canonical_path)",
    )
    parser.add_argument(
        "--mode",
        choices=["exact", "both"],
        default="both",
        help="Dedup mode: exact hash only, or both exact+MinHash (default: both)",
    )
    parser.add_argument(
        "--ref",
        help="Reference JSONL for cross-split deduplication",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers for MinHash (default: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stats without writing output",
    )
    parser.add_argument(
        "--keep-removed",
        action="store_true",
        help="Include removed records in output (with dedup_kept=false)",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.output:
        parser.error("--output is required unless --dry-run is specified")

    dd = DatasetDeduplicator(
        threshold=args.threshold,
        keep=args.keep,
        mode=args.mode,
        workers=args.workers,
    )

    report = dd.deduplicate(
        input_path=args.input_path,
        output_path=args.output,
        ref_path=args.ref,
        dry_run=args.dry_run,
        keep_removed=args.keep_removed,
    )

    print("Deduplication Report:")
    print(f"  Total input:              {report.total_input}")
    print(f"  Total output:             {report.total_output}")
    print(f"  Exact duplicates removed: {report.exact_duplicates_removed}")
    print(f"  Near duplicates removed:  {report.near_duplicates_removed}")
    print(f"  Ref duplicates removed:   {report.ref_duplicates_removed}")
    print(f"  Clusters:                 {report.cluster_count}")
    print(f"  Dedup rate:               {report.dedup_rate:.1%}")


if __name__ == "__main__":
    main()
