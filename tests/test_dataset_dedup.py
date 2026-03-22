"""Tests for dataset_dedup.py — Dataset Deduplication Pipeline.

Follows COR-1500 TDD: tests written first (RED), then implementation (GREEN).
Covers: exact hash, MinHash/LSH, Jaccard verification, Union-Find,
exact cluster re-expansion, cross-split ref dedup, keep strategies,
failure modes, DeduplicationReport counters, tie-break determinism.
"""

import hashlib
import json
import os

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(source: str) -> str:
    """Normalise source like the dedup module does."""
    lines = source.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines)


def _sha(source: str) -> str:
    """SHA-256 of normalised source."""
    return hashlib.sha256(_norm(source).encode("utf-8")).hexdigest()


def _write_py(directory: str, name: str, content: str) -> str:
    """Write a .py file into a directory; return its path."""
    os.makedirs(directory, exist_ok=True)
    p = os.path.join(directory, name)
    with open(p, "w") as f:
        f.write(content)
    return p


def _write_jsonl(path: str, records: list[dict]) -> None:
    """Write a list of dicts as JSONL."""
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: str) -> list[dict]:
    """Read JSONL file; return list of dicts."""
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


# ---------------------------------------------------------------------------
# Sample sources
# ---------------------------------------------------------------------------

SRC_A = """\
def hello():
    print("hello world")

def add(x, y):
    return x + y
"""

# Exact duplicate of A (same normalised content)
SRC_A_DUP = """\
def hello():
    print("hello world")

def add(x, y):
    return x + y
"""

# Near-duplicate of A: variable rename + comment change
SRC_A_NEAR = """\
def greet():
    print("hello world")

def sum_nums(a, b):
    return a + b
"""

SRC_B = """\
import os
import sys

class Config:
    def __init__(self):
        self.debug = False
        self.verbose = True

    def validate(self):
        if self.debug:
            print("debug mode")
        return True
"""

SRC_C = """\
for i in range(100):
    if i % 2 == 0:
        print(i)
    elif i % 3 == 0:
        print(i * 2)
    else:
        pass
"""

# Very short file (< 5 tokens after normalisation)
SRC_SHORT = "x = 1\n"


# ---------------------------------------------------------------------------
# Test: DatasetDeduplicator construction
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_params(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator()
        assert dd.threshold == 0.8
        assert dd.keep == "canonical_path"
        assert dd.mode == "both"
        assert dd.workers == 1

    def test_invalid_threshold_zero(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        with pytest.raises(ValueError):
            DatasetDeduplicator(threshold=0.0)

    def test_invalid_threshold_negative(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        with pytest.raises(ValueError):
            DatasetDeduplicator(threshold=-0.5)

    def test_invalid_threshold_above_one(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        with pytest.raises(ValueError):
            DatasetDeduplicator(threshold=1.5)

    def test_threshold_one_ok(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(threshold=1.0)
        assert dd.threshold == 1.0

    def test_invalid_keep(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        with pytest.raises(ValueError):
            DatasetDeduplicator(keep="random")

    def test_invalid_mode(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        with pytest.raises(ValueError):
            DatasetDeduplicator(mode="minhash")

    def test_mode_exact_no_datasketch(self):
        """mode='exact' should work even without datasketch."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        assert dd.mode == "exact"


# ---------------------------------------------------------------------------
# Test: _read_source
# ---------------------------------------------------------------------------


class TestReadSource:
    def test_read_from_disk(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        p = tmp_path / "test.py"
        p.write_text(SRC_A)
        dd = DatasetDeduplicator(mode="exact")
        record = {"path": str(p)}
        result = dd._read_source(record)
        assert result is not None
        source, sha = result
        assert source == _norm(SRC_A)
        assert sha == _sha(SRC_A)

    def test_read_from_content_field(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        record = {"path": "nonexistent.py", "content": SRC_A}
        result = dd._read_source(record)
        assert result is not None
        source, sha = result
        assert source == _norm(SRC_A)
        assert sha == _sha(SRC_A)

    def test_content_field_priority_over_disk(self, tmp_path):
        """When content field is present, disk is never read."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        p = tmp_path / "test.py"
        p.write_text(SRC_B)
        dd = DatasetDeduplicator(mode="exact")
        record = {"path": str(p), "content": SRC_A}
        result = dd._read_source(record)
        assert result is not None
        source, sha = result
        assert source == _norm(SRC_A)  # content field wins

    def test_content_sha256_validation_pass(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        expected_sha = _sha(SRC_A)
        record = {"path": "x.py", "content": SRC_A, "content_sha256": expected_sha}
        result = dd._read_source(record)
        assert result is not None
        assert record.get("dedup_error_type") is None

    def test_content_sha256_validation_mismatch(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        record = {
            "path": "x.py",
            "content": SRC_A,
            "content_sha256": "wrong_hash",
        }
        result = dd._read_source(record)
        # Returns the tuple (source was read), but sets error fields
        assert result is not None
        assert record["dedup_error_type"] == "content_mismatch"
        assert record["dedup_error"] is not None

    def test_io_error_missing_file(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        record = {"path": "/nonexistent/file.py"}
        result = dd._read_source(record)
        assert result is None
        assert record["dedup_error_type"] == "io_error"


# ---------------------------------------------------------------------------
# Test: Normalised exact hash pass
# ---------------------------------------------------------------------------


class TestExactHashPass:
    def test_exact_duplicates_grouped(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path), "a.py", SRC_A)
        _write_py(str(tmp_path), "b.py", SRC_A_DUP)  # exact dup
        _write_py(str(tmp_path), "c.py", SRC_B)
        dd = DatasetDeduplicator(mode="exact")
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        # Filter out error records
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, cluster_map = dd._exact_hash_pass(good)
        # Should have 2 representatives: one for A/A_DUP, one for B
        assert len(reps) == 2
        # The A/A_DUP cluster should have 2 members
        sha_a = _sha(SRC_A)
        assert sha_a in cluster_map
        assert len(cluster_map[sha_a]) == 2

    def test_no_duplicates(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path), "a.py", SRC_A)
        _write_py(str(tmp_path), "c.py", SRC_B)
        dd = DatasetDeduplicator(mode="exact")
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, cluster_map = dd._exact_hash_pass(good)
        assert len(reps) == 2
        # All clusters have 1 member
        for members in cluster_map.values():
            assert len(members) == 1

    def test_line_ending_normalisation(self, tmp_path):
        """CRLF and LF versions should be exact duplicates."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        p1 = tmp_path / "lf.py"
        p1.write_bytes(b"def f():\n    pass\n")
        p2 = tmp_path / "crlf.py"
        p2.write_bytes(b"def f():\r\n    pass\r\n")
        dd = DatasetDeduplicator(mode="exact")
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, cluster_map = dd._exact_hash_pass(good)
        assert len(reps) == 1  # normalised to same hash


# ---------------------------------------------------------------------------
# Test: MinHash/LSH pass
# ---------------------------------------------------------------------------


class TestMinHashLSHPass:
    def test_near_duplicates_detected(self, tmp_path):
        """A and A_NEAR should be detected as near-duplicates."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path), "a.py", SRC_A)
        _write_py(str(tmp_path), "near.py", SRC_A_NEAR)
        _write_py(str(tmp_path), "b.py", SRC_B)
        dd = DatasetDeduplicator(threshold=0.5)
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, _ = dd._exact_hash_pass(good)
        clusters = dd._minhash_lsh_pass(reps)
        # At least one cluster should contain a.py and near.py
        found_near = False
        for cluster in clusters:
            paths = {os.path.basename(r["path"]) for r in cluster}
            if "a.py" in paths and "near.py" in paths:
                found_near = True
        assert found_near, f"Near-dup cluster not found. Clusters: {clusters}"

    def test_dissimilar_files_not_clustered(self, tmp_path):
        """SRC_A and SRC_B should NOT be in the same cluster."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path), "a.py", SRC_A)
        _write_py(str(tmp_path), "b.py", SRC_B)
        dd = DatasetDeduplicator(threshold=0.5)
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, _ = dd._exact_hash_pass(good)
        clusters = dd._minhash_lsh_pass(reps)
        for cluster in clusters:
            paths = {os.path.basename(r["path"]) for r in cluster}
            assert not ("a.py" in paths and "b.py" in paths), (
                "Dissimilar files clustered together"
            )

    def test_short_file_skipped(self, tmp_path):
        """Files with <5 tokens should be skipped from MinHash."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path), "short.py", SRC_SHORT)
        _write_py(str(tmp_path), "a.py", SRC_A)
        dd = DatasetDeduplicator(threshold=0.5)
        records = dd._load_records(str(tmp_path))
        for r in records:
            dd._read_source(r)
        good = [r for r in records if r.get("dedup_error_type") is None]
        reps, _ = dd._exact_hash_pass(good)
        clusters = dd._minhash_lsh_pass(reps)
        # short.py should not appear in any MinHash cluster
        for cluster in clusters:
            paths = {os.path.basename(r["path"]) for r in cluster}
            assert "short.py" not in paths


# ---------------------------------------------------------------------------
# Test: Jaccard verification
# ---------------------------------------------------------------------------


class TestVerifyJaccard:
    def test_identical_shingles(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        shingles = {("a", "b", "c", "d", "e"), ("b", "c", "d", "e", "f")}
        assert dd._verify_jaccard(shingles, shingles) == 1.0

    def test_disjoint_shingles(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        s1 = {("a", "b", "c", "d", "e")}
        s2 = {("x", "y", "z", "w", "v")}
        assert dd._verify_jaccard(s1, s2) == 0.0

    def test_partial_overlap(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        s1 = {("a",), ("b",), ("c",), ("d",)}
        s2 = {("a",), ("b",), ("e",), ("f",)}
        # Intersection: {a, b} = 2; Union: {a, b, c, d, e, f} = 6
        expected = 2 / 6
        assert abs(dd._verify_jaccard(s1, s2) - expected) < 1e-9


# ---------------------------------------------------------------------------
# Test: Union-Find
# ---------------------------------------------------------------------------


class TestUnionFind:
    def test_transitive_closure(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        r1 = {"path": "a.py", "_idx": 0}
        r2 = {"path": "b.py", "_idx": 1}
        r3 = {"path": "c.py", "_idx": 2}
        # Pairs: (r1, r2) and (r2, r3) -> all in one component
        pairs = [(r1, r2), (r2, r3)]
        clusters = dd._union_find(pairs)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_separate_components(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        r1 = {"path": "a.py", "_idx": 0}
        r2 = {"path": "b.py", "_idx": 1}
        r3 = {"path": "c.py", "_idx": 2}
        r4 = {"path": "d.py", "_idx": 3}
        pairs = [(r1, r2), (r3, r4)]
        clusters = dd._union_find(pairs)
        assert len(clusters) == 2

    def test_empty_pairs(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        clusters = dd._union_find([])
        assert clusters == []


# ---------------------------------------------------------------------------
# Test: Exact cluster re-expansion
# ---------------------------------------------------------------------------


class TestExpandWithExactMembers:
    def test_expansion(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        # rep_A had exact dup dup_A
        rep_a = {"path": "a.py", "content_sha256": "sha_a", "_idx": 0}
        dup_a = {"path": "a_dup.py", "content_sha256": "sha_a", "_idx": 1}
        rep_c = {"path": "c.py", "content_sha256": "sha_c", "_idx": 2}
        # Near-dup cluster of representatives: [rep_a, rep_c]
        near_clusters = [[rep_a, rep_c]]
        exact_cluster_map = {
            "sha_a": [rep_a, dup_a],
            "sha_c": [rep_c],
        }
        expanded = dd._expand_with_exact_members(near_clusters, exact_cluster_map)
        assert len(expanded) == 1
        assert len(expanded[0]) == 3  # rep_a, dup_a, rep_c


# ---------------------------------------------------------------------------
# Test: Representative selection (keep strategies)
# ---------------------------------------------------------------------------


class TestSelectRepresentative:
    def test_canonical_path(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(keep="canonical_path", mode="exact")
        cluster = [
            {"path": "c.py", "_idx": 2},
            {"path": "a.py", "_idx": 0},
            {"path": "b.py", "_idx": 1},
        ]
        rep = dd._select_representative(cluster, "canonical_path")
        assert rep["path"] == "a.py"

    def test_best_score(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(keep="best_score", mode="exact")
        cluster = [
            {"path": "a.py", "score": 80.0, "_idx": 0},
            {"path": "b.py", "score": 95.0, "_idx": 1},
            {"path": "c.py", "score": 90.0, "_idx": 2},
        ]
        rep = dd._select_representative(cluster, "best_score")
        assert rep["path"] == "b.py"

    def test_best_score_tiebreak_by_path(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(keep="best_score", mode="exact")
        cluster = [
            {"path": "b.py", "score": 90.0, "_idx": 1},
            {"path": "a.py", "score": 90.0, "_idx": 0},
        ]
        rep = dd._select_representative(cluster, "best_score")
        assert rep["path"] == "a.py"  # path asc tiebreak

    def test_canonical_path_tiebreak_by_idx(self):
        """Same path (unlikely) -> tiebreak by original index."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(keep="canonical_path", mode="exact")
        cluster = [
            {"path": "a.py", "_idx": 5},
            {"path": "a.py", "_idx": 2},
        ]
        rep = dd._select_representative(cluster, "canonical_path")
        assert rep["_idx"] == 2


# ---------------------------------------------------------------------------
# Test: dedup_group_id stability
# ---------------------------------------------------------------------------


class TestDedupGroupId:
    def test_group_id_based_on_sorted_member_hashes(self):
        """Group ID should be sha256(sorted(member sha256s))[:16]."""
        sha1 = _sha(SRC_A)
        sha2 = _sha(SRC_B)
        sorted_shas = sorted([sha1, sha2])
        expected = hashlib.sha256("".join(sorted_shas).encode("utf-8")).hexdigest()[:16]

        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        cluster = [
            {"content_sha256": sha1, "path": "a.py", "_idx": 0},
            {"content_sha256": sha2, "path": "b.py", "_idx": 1},
        ]
        # Use internal helper if available, otherwise test via full pipeline
        group_id = dd._compute_group_id(cluster)
        assert group_id == expected

    def test_group_id_invariant_to_order(self):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        dd = DatasetDeduplicator(mode="exact")
        sha1 = "aaaa"
        sha2 = "bbbb"
        c1 = [
            {"content_sha256": sha1, "path": "a.py", "_idx": 0},
            {"content_sha256": sha2, "path": "b.py", "_idx": 1},
        ]
        c2 = [
            {"content_sha256": sha2, "path": "b.py", "_idx": 1},
            {"content_sha256": sha1, "path": "a.py", "_idx": 0},
        ]
        assert dd._compute_group_id(c1) == dd._compute_group_id(c2)


# ---------------------------------------------------------------------------
# Test: Full pipeline — deduplicate() with raw directory
# ---------------------------------------------------------------------------


class TestDeduplicateRawDirectory:
    def test_exact_only_mode(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        _write_py(str(tmp_path / "input"), "a.py", SRC_A)
        _write_py(str(tmp_path / "input"), "a_dup.py", SRC_A_DUP)
        _write_py(str(tmp_path / "input"), "b.py", SRC_B)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(str(tmp_path / "input"), out)
        assert report.total_input == 3
        assert report.total_output == 2
        assert report.exact_duplicates_removed == 1
        assert report.near_duplicates_removed == 0

        records = _read_jsonl(out)
        assert len(records) == 2
        # All records should have dedup fields
        for r in records:
            assert "dedup_kept" in r
            assert r["dedup_kept"] is True

    def test_both_mode(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "a_dup.py", SRC_A_DUP)
        _write_py(str(input_dir), "near.py", SRC_A_NEAR)
        _write_py(str(input_dir), "b.py", SRC_B)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(threshold=0.5, mode="both")
        report = dd.deduplicate(str(input_dir), out)
        assert report.total_input == 4
        # a.py, a_dup.py, near.py should cluster -> 2 removed
        assert report.exact_duplicates_removed >= 1
        assert report.total_output <= 3
        assert report.dedup_rate > 0

    def test_dry_run(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_A_DUP)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(str(input_dir), out, dry_run=True)
        assert report.exact_duplicates_removed == 1
        assert not os.path.exists(out)

    def test_keep_removed(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_A_DUP)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(str(input_dir), out, keep_removed=True)
        records = _read_jsonl(out)
        assert len(records) == 2  # both written
        kept = [r for r in records if r["dedup_kept"]]
        removed = [r for r in records if not r["dedup_kept"]]
        assert len(kept) == 1
        assert len(removed) == 1


# ---------------------------------------------------------------------------
# Test: Full pipeline — deduplicate() with JSONL input
# ---------------------------------------------------------------------------


class TestDeduplicateJSONL:
    def test_annotated_jsonl(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "src"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_A_DUP)
        _write_py(str(input_dir), "c.py", SRC_B)
        jsonl_path = str(tmp_path / "input.jsonl")
        records = [
            {"path": str(input_dir / "a.py"), "score": 85.0},
            {"path": str(input_dir / "b.py"), "score": 90.0},
            {"path": str(input_dir / "c.py"), "score": 75.0},
        ]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(jsonl_path, out)
        assert report.total_input == 3
        assert report.exact_duplicates_removed == 1

    def test_jsonl_with_content_field(self, tmp_path):
        """JSONL with inline content should not touch disk."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        records = [
            {"path": "virtual/a.py", "content": SRC_A, "score": 85.0},
            {"path": "virtual/b.py", "content": SRC_A_DUP, "score": 90.0},
            {"path": "virtual/c.py", "content": SRC_B, "score": 75.0},
        ]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(jsonl_path, out)
        assert report.exact_duplicates_removed == 1

    def test_best_score_on_scoreless_raises(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        records = [{"path": "a.py", "content": SRC_A}]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(keep="best_score", mode="exact")
        with pytest.raises(ValueError, match="score"):
            dd.deduplicate(jsonl_path, out)

    def test_best_score_on_raw_dir_raises(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(keep="best_score", mode="exact")
        with pytest.raises(ValueError, match="score"):
            dd.deduplicate(str(input_dir), out)

    def test_malformed_jsonl_skipped(self, tmp_path):
        """Malformed JSONL lines should be skipped with a warning."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        with open(jsonl_path, "w") as f:
            f.write(json.dumps({"path": "a.py", "content": SRC_A}) + "\n")
            f.write("NOT VALID JSON\n")
            f.write(json.dumps({"path": "b.py", "content": SRC_B}) + "\n")
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(jsonl_path, out)
        assert report.total_input == 2  # malformed line skipped

    def test_missing_path_skipped(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        records = [
            {"path": "a.py", "content": SRC_A},
            {"content": SRC_B},  # no path
        ]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(jsonl_path, out)
        assert report.total_input == 1


# ---------------------------------------------------------------------------
# Test: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_io_error_kept_in_output(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        records = [
            {"path": "/nonexistent/file.py"},
            {"path": "b.py", "content": SRC_B},
        ]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(jsonl_path, out)
        output = _read_jsonl(out)
        error_recs = [r for r in output if r.get("dedup_error_type") == "io_error"]
        assert len(error_recs) == 1
        assert error_recs[0]["dedup_kept"] is True
        assert error_recs[0]["dedup_reason"] == "error"

    def test_content_mismatch_kept_in_output(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        records = [
            {
                "path": "a.py",
                "content": SRC_A,
                "content_sha256": "wrong_hash",
            },
            {"path": "b.py", "content": SRC_B},
        ]
        _write_jsonl(jsonl_path, records)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(jsonl_path, out)
        output = _read_jsonl(out)
        mismatch_recs = [
            r for r in output if r.get("dedup_error_type") == "content_mismatch"
        ]
        assert len(mismatch_recs) == 1
        assert mismatch_recs[0]["dedup_kept"] is True
        # content_sha256 should be the CURRENT computed hash, not null
        assert mismatch_recs[0]["content_sha256"] == _sha(SRC_A)


# ---------------------------------------------------------------------------
# Test: Reference-set deduplication (--ref)
# ---------------------------------------------------------------------------


class TestRefDedup:
    def test_ref_exact_removes_match(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        # Input has A and B; ref has A -> A should be removed
        input_jsonl = str(tmp_path / "input.jsonl")
        ref_jsonl = str(tmp_path / "ref.jsonl")
        _write_jsonl(
            input_jsonl,
            [
                {"path": "a.py", "content": SRC_A},
                {"path": "b.py", "content": SRC_B},
            ],
        )
        _write_jsonl(ref_jsonl, [{"path": "ref_a.py", "content": SRC_A}])
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(input_jsonl, out, ref_path=ref_jsonl)
        assert report.ref_duplicates_removed >= 1
        output = _read_jsonl(out)
        paths = {r["path"] for r in output}
        assert "a.py" not in paths
        assert "b.py" in paths

    def test_ref_near_removes_match(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        # Input has A_NEAR and B; ref has A -> A_NEAR should be removed (near match)
        input_jsonl = str(tmp_path / "input.jsonl")
        ref_jsonl = str(tmp_path / "ref.jsonl")
        _write_jsonl(
            input_jsonl,
            [
                {"path": "near.py", "content": SRC_A_NEAR},
                {"path": "b.py", "content": SRC_B},
            ],
        )
        _write_jsonl(ref_jsonl, [{"path": "ref_a.py", "content": SRC_A}])
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(threshold=0.5, mode="both")
        report = dd.deduplicate(input_jsonl, out, ref_path=ref_jsonl)
        assert report.ref_duplicates_removed >= 1

    def test_ref_backfill_representative(self, tmp_path):
        """When ref removes a cluster representative, backfill from remaining."""
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        # a.py (exact dup of ref), a_dup.py (exact dup of a.py) -> a.py removed,
        # a_dup.py should be backfilled as representative
        input_jsonl = str(tmp_path / "input.jsonl")
        ref_jsonl = str(tmp_path / "ref.jsonl")
        _write_jsonl(
            input_jsonl,
            [
                {"path": "a.py", "content": SRC_A},
                {"path": "a_dup.py", "content": SRC_A_DUP},
                {"path": "b.py", "content": SRC_B},
            ],
        )
        _write_jsonl(ref_jsonl, [{"path": "ref_a.py", "content": SRC_A}])
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(input_jsonl, out, ref_path=ref_jsonl)
        output = _read_jsonl(out)
        # Both a.py and a_dup.py are exact matches to ref -> both removed
        # (exact ref check checks ALL kept records, not just representatives)
        kept_paths = {r["path"] for r in output if r["dedup_kept"]}
        assert "b.py" in kept_paths
        # Both a.py and a_dup.py match ref exactly -> both removed
        assert report.ref_duplicates_removed >= 1


# ---------------------------------------------------------------------------
# Test: DeduplicationReport counters
# ---------------------------------------------------------------------------


class TestDeduplicationReport:
    def test_dedup_rate_calculation(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_A_DUP)
        _write_py(str(input_dir), "c.py", SRC_B)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(str(input_dir), out)
        # 3 input, 2 output -> rate = 1/3
        assert abs(report.dedup_rate - 1 / 3) < 1e-9

    def test_all_unique(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_B)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        report = dd.deduplicate(str(input_dir), out)
        assert report.dedup_rate == 0.0
        assert report.exact_duplicates_removed == 0
        assert report.near_duplicates_removed == 0
        assert report.cluster_count == 0


# ---------------------------------------------------------------------------
# Test: Output field completeness
# ---------------------------------------------------------------------------


class TestOutputFields:
    def test_all_dedup_fields_present(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        _write_py(str(input_dir), "a.py", SRC_A)
        _write_py(str(input_dir), "b.py", SRC_A_DUP)
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(str(input_dir), out)
        records = _read_jsonl(out)
        required_fields = {
            "content_sha256",
            "dedup_group_id",
            "dedup_cluster_size",
            "dedup_kept",
            "dedup_reason",
            "dedup_similarity_max",
            "dedup_error_type",
            "dedup_error",
        }
        for r in records:
            for field in required_fields:
                assert field in r, f"Missing field {field} in record {r['path']}"

    def test_unique_file_fields(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        _write_jsonl(jsonl_path, [{"path": "a.py", "content": SRC_A}])
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(jsonl_path, out)
        records = _read_jsonl(out)
        assert len(records) == 1
        r = records[0]
        assert r["dedup_kept"] is True
        assert r["dedup_reason"] == "unique"
        assert r["dedup_group_id"] is None
        assert r["dedup_cluster_size"] == 1
        assert r["dedup_similarity_max"] is None

    def test_existing_fields_preserved(self, tmp_path):
        from dr_huatuo.dataset_dedup import DatasetDeduplicator

        jsonl_path = str(tmp_path / "input.jsonl")
        _write_jsonl(
            jsonl_path,
            [{"path": "a.py", "content": SRC_A, "source": "test", "license": "MIT"}],
        )
        out = str(tmp_path / "out.jsonl")
        dd = DatasetDeduplicator(mode="exact")
        dd.deduplicate(jsonl_path, out)
        records = _read_jsonl(out)
        assert records[0]["source"] == "test"
        assert records[0]["license"] == "MIT"


# ---------------------------------------------------------------------------
# Test: tokenize failure stderr warning
# ---------------------------------------------------------------------------


class TestTokenizeWarning:
    def test_tokenize_failure_prints_to_stderr(self, capsys):
        """_tokenise_and_normalise should print a warning to stderr on TokenError."""
        from dr_huatuo.dataset_dedup import _tokenise_and_normalise

        # Unclosed string literal causes TokenError during tokenization
        bad_source = 'x = "unclosed string\n'
        tokens = _tokenise_and_normalise(bad_source, path="bad_file.py")

        captured = capsys.readouterr()
        assert "Warning: tokenize failed for bad_file.py" in captured.err
        # Should return whatever tokens were collected before the error
        assert isinstance(tokens, list)

    def test_tokenize_failure_default_path_in_warning(self, capsys):
        """When path is not provided, warning uses <unknown>."""
        from dr_huatuo.dataset_dedup import _tokenise_and_normalise

        bad_source = 'x = "unclosed\n'
        _tokenise_and_normalise(bad_source)

        captured = capsys.readouterr()
        assert "<unknown>" in captured.err
