"""Tests for bugsinpy_analysis.py.

Covers: path-based pairing, Cohen's d computation, null exclusion,
paired join logic, effect size labels, stats computation, report
generation, and data structures.
"""

import statistics

import pytest

from bugsinpy_analysis import (
    _NUMERIC_METRICS,
    _PAIR_REGEX,
    AnalysisReport,
    BugsInPyAnalysis,
    PairedResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analysis(tmp_path):
    """Create a BugsInPyAnalysis with tmp paths."""
    project_dir = tmp_path / "thefuck"
    project_dir.mkdir()
    return BugsInPyAnalysis(
        data_root=str(tmp_path),
        project="thefuck",
    )


def _make_record(path, score=80.0, ruff_violations=2, error_type=None, **kwargs):
    """Helper to build a mock annotated record."""
    record = {
        "path": path,
        "score": score,
        "ruff_violations": ruff_violations,
        "bandit_high": 0,
        "bandit_medium": 0,
        "mypy_errors": 0,
        "pylint_score": 5.0,
        "loc": 50,
        "function_count": 3,
        "class_count": 0,
        "cyclomatic_complexity": 5,
        "avg_complexity": 3.0,
        "cognitive_complexity": 4,
        "max_nesting_depth": 2,
        "halstead_volume": 500.0,
        "halstead_difficulty": 10.0,
        "halstead_effort": 5000.0,
        "maintainability_index": 60.0,
        "fanout_modules": 3,
        "fanout_symbols": 5,
        "comment_density": 0.1,
        "docstring_density": 0.5,
        "error_type": error_type,
        "error_detail": None,
        "data_warnings": [],
        "tool_errors": None,
    }
    record.update(kwargs)
    return record


# ---------------------------------------------------------------------------
# Path-based pairing regex
# ---------------------------------------------------------------------------


class TestPairRegex:
    def test_buggy_path(self):
        path = "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py"
        m = _PAIR_REGEX.match(path)
        assert m is not None
        assert m.group("variant") == "buggy"
        assert m.group("bug_id") == "1"
        assert m.group("affected_file") == "thefuck/rules/pip.py"

    def test_fixed_path(self):
        path = "data/bugsinpy/thefuck/fixed/bug_16/thefuck/shells/bash.py"
        m = _PAIR_REGEX.match(path)
        assert m is not None
        assert m.group("variant") == "fixed"
        assert m.group("bug_id") == "16"
        assert m.group("affected_file") == "thefuck/shells/bash.py"

    def test_absolute_path(self):
        path = "/home/user/data/bugsinpy/thefuck/buggy/bug_3/foo/bar.py"
        m = _PAIR_REGEX.match(path)
        assert m is not None
        assert m.group("bug_id") == "3"

    def test_no_match(self):
        path = "some/other/path.py"
        m = _PAIR_REGEX.match(path)
        assert m is None

    def test_multi_digit_bug_id(self):
        path = "data/bugsinpy/thefuck/buggy/bug_123/thefuck/app.py"
        m = _PAIR_REGEX.match(path)
        assert m is not None
        assert m.group("bug_id") == "123"


# ---------------------------------------------------------------------------
# PairedResult and AnalysisReport dataclasses
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_paired_result_defaults(self):
        pr = PairedResult()
        assert pr.metric == ""
        assert pr.n_pairs == 0
        assert pr.cohens_d == 0.0
        assert pr.excluded is False

    def test_analysis_report_defaults(self):
        ar = AnalysisReport()
        assert ar.project == ""
        assert ar.total_buggy == 0
        assert ar.paired_results == []
        assert ar.excluded_metrics == []
        assert ar.within_buggy_dedup is None


# ---------------------------------------------------------------------------
# _parse_pairing
# ---------------------------------------------------------------------------


class TestParsePairing:
    def test_valid_buggy(self, analysis):
        result = analysis._parse_pairing(
            "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py"
        )
        assert result == (1, "buggy", "thefuck/rules/pip.py")

    def test_valid_fixed(self, analysis):
        result = analysis._parse_pairing(
            "data/bugsinpy/thefuck/fixed/bug_5/thefuck/app.py"
        )
        assert result == (5, "fixed", "thefuck/app.py")

    def test_invalid_path(self, analysis):
        result = analysis._parse_pairing("some/random/path.py")
        assert result is None


# ---------------------------------------------------------------------------
# Cohen's d computation (_compute_paired_metric)
# ---------------------------------------------------------------------------


class TestComputePairedMetric:
    def test_basic_cohens_d(self, analysis):
        """Cohen's d = mean(delta) / std(delta)."""
        buggy = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", score=70.0)
        fixed = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", score=80.0)
        buggy2 = _make_record("data/bugsinpy/t/buggy/bug_2/a.py", score=60.0)
        fixed2 = _make_record("data/bugsinpy/t/fixed/bug_2/a.py", score=90.0)

        pairs = [(buggy, fixed), (buggy2, fixed2)]
        pr = analysis._compute_paired_metric("score", pairs)

        # deltas: 10, 30 => mean=20, std=~14.14
        assert pr.metric == "score"
        assert pr.n_pairs == 2
        assert pr.mean_delta == pytest.approx(20.0)
        expected_d = 20.0 / statistics.stdev([10.0, 30.0])
        assert pr.cohens_d == pytest.approx(expected_d)

    def test_zero_std(self, analysis):
        """All deltas are the same -> std=0 -> Cohen's d = inf or 0."""
        buggy = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", score=70.0)
        fixed = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", score=80.0)
        buggy2 = _make_record("data/bugsinpy/t/buggy/bug_2/a.py", score=70.0)
        fixed2 = _make_record("data/bugsinpy/t/fixed/bug_2/a.py", score=80.0)

        pairs = [(buggy, fixed), (buggy2, fixed2)]
        pr = analysis._compute_paired_metric("score", pairs)

        # deltas: 10, 10 => mean=10, std=0 => d=inf
        assert pr.cohens_d == float("inf")

    def test_zero_delta(self, analysis):
        """All deltas are zero -> Cohen's d = 0."""
        buggy = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", score=80.0)
        fixed = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", score=80.0)
        buggy2 = _make_record("data/bugsinpy/t/buggy/bug_2/a.py", score=80.0)
        fixed2 = _make_record("data/bugsinpy/t/fixed/bug_2/a.py", score=80.0)

        pairs = [(buggy, fixed), (buggy2, fixed2)]
        pr = analysis._compute_paired_metric("score", pairs)

        assert pr.cohens_d == 0.0

    def test_single_pair(self, analysis):
        """Single pair -> std=0 -> special case."""
        buggy = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", score=70.0)
        fixed = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", score=80.0)

        pairs = [(buggy, fixed)]
        pr = analysis._compute_paired_metric("score", pairs)

        assert pr.n_pairs == 1
        assert pr.mean_delta == 10.0
        assert pr.cohens_d == float("inf")

    def test_negative_delta(self, analysis):
        """Fixed worse than buggy -> negative Cohen's d."""
        buggy = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", ruff_violations=2)
        fixed = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", ruff_violations=5)
        buggy2 = _make_record("data/bugsinpy/t/buggy/bug_2/a.py", ruff_violations=1)
        fixed2 = _make_record("data/bugsinpy/t/fixed/bug_2/a.py", ruff_violations=3)

        pairs = [(buggy, fixed), (buggy2, fixed2)]
        pr = analysis._compute_paired_metric("ruff_violations", pairs)

        # delta: 3, 2 => mean=2.5 (positive means fixed has MORE violations)
        assert pr.mean_delta > 0
        assert pr.cohens_d > 0

    def test_pct_fixed_better(self, analysis):
        """pct_fixed_better counts positive deltas."""
        buggy1 = _make_record("data/bugsinpy/t/buggy/bug_1/a.py", score=70)
        fixed1 = _make_record("data/bugsinpy/t/fixed/bug_1/a.py", score=80)
        buggy2 = _make_record("data/bugsinpy/t/buggy/bug_2/a.py", score=90)
        fixed2 = _make_record("data/bugsinpy/t/fixed/bug_2/a.py", score=85)

        pairs = [(buggy1, fixed1), (buggy2, fixed2)]
        pr = analysis._compute_paired_metric("score", pairs)

        # delta1=10 (positive), delta2=-5 (negative)
        assert pr.pct_fixed_better == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Null exclusion
# ---------------------------------------------------------------------------


class TestNullExclusion:
    def test_high_null_rate_excluded(self, analysis):
        """Metrics with >30% null rate should be excluded."""
        records_with_null = [
            (
                _make_record("data/bugsinpy/t/buggy/bug_1/a.py", pylint_score=None),
                _make_record("data/bugsinpy/t/fixed/bug_1/a.py", pylint_score=5.0),
            ),
            (
                _make_record("data/bugsinpy/t/buggy/bug_2/a.py", pylint_score=None),
                _make_record("data/bugsinpy/t/fixed/bug_2/a.py", pylint_score=6.0),
            ),
            (
                _make_record("data/bugsinpy/t/buggy/bug_3/a.py", pylint_score=4.0),
                _make_record("data/bugsinpy/t/fixed/bug_3/a.py", pylint_score=7.0),
            ),
        ]
        pr = analysis._compute_paired_metric("pylint_score", records_with_null)
        # 2 out of 3 pairs have null -> 66.7% null rate
        assert pr.excluded is True
        assert "null_rate" in pr.exclude_reason

    def test_acceptable_null_rate_not_excluded(self, analysis):
        """Metrics with <=30% null rate should not be excluded."""
        pairs = []
        for i in range(10):
            buggy = _make_record(
                f"data/bugsinpy/t/buggy/bug_{i}/a.py",
                score=70.0 + i,
            )
            fixed = _make_record(
                f"data/bugsinpy/t/fixed/bug_{i}/a.py",
                score=80.0 + i,
            )
            pairs.append((buggy, fixed))

        pr = analysis._compute_paired_metric("score", pairs)
        assert pr.excluded is False

    def test_no_valid_pairs_excluded(self, analysis):
        """Zero valid pairs should be excluded."""
        pr = analysis._compute_paired_metric("score", [])
        assert pr.excluded is True
        # With 0 pairs, null_rate is 1.0 (100%), triggering null_rate exclusion
        assert "null_rate" in pr.exclude_reason or "no valid pairs" in pr.exclude_reason


# ---------------------------------------------------------------------------
# Paired join logic (_paired_analysis)
# ---------------------------------------------------------------------------


class TestPairedAnalysis:
    def test_matching_pairs(self, analysis):
        """Records with matching (bug_id, affected_file) should be paired."""
        buggy_records = [
            _make_record(
                "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py",
                score=70.0,
            ),
            _make_record(
                "data/bugsinpy/thefuck/buggy/bug_2/thefuck/app.py",
                score=60.0,
            ),
        ]
        fixed_records = [
            _make_record(
                "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py",
                score=85.0,
            ),
            _make_record(
                "data/bugsinpy/thefuck/fixed/bug_2/thefuck/app.py",
                score=90.0,
            ),
        ]

        results, excluded, stats = analysis._paired_analysis(
            buggy_records, fixed_records
        )

        assert stats["total_pairs"] == 2
        assert stats["unmatched_buggy"] == 0
        assert stats["unmatched_fixed"] == 0

    def test_unmatched_records(self, analysis):
        """Records without matching counterpart should be counted as unmatched."""
        buggy_records = [
            _make_record(
                "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py",
                score=70.0,
            ),
            _make_record(
                "data/bugsinpy/thefuck/buggy/bug_3/thefuck/new.py",
                score=50.0,
            ),
        ]
        fixed_records = [
            _make_record(
                "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py",
                score=85.0,
            ),
        ]

        results, excluded, stats = analysis._paired_analysis(
            buggy_records, fixed_records
        )

        assert stats["total_pairs"] == 1
        assert stats["unmatched_buggy"] == 1
        assert stats["unmatched_fixed"] == 0

    def test_error_records_excluded_from_pairs(self, analysis):
        """Records with error_type should be excluded from paired analysis."""
        buggy_records = [
            _make_record(
                "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py",
                score=70.0,
                error_type="syntax_error",
            ),
        ]
        fixed_records = [
            _make_record(
                "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py",
                score=85.0,
            ),
        ]

        results, excluded, stats = analysis._paired_analysis(
            buggy_records, fixed_records
        )

        assert stats["total_pairs"] == 0

    def test_unparseable_paths_ignored(self, analysis):
        """Records with paths that don't match the regex should be ignored."""
        buggy_records = [
            _make_record("some/random/path.py", score=70.0),
        ]
        fixed_records = [
            _make_record(
                "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py",
                score=85.0,
            ),
        ]

        results, excluded, stats = analysis._paired_analysis(
            buggy_records, fixed_records
        )

        assert stats["total_pairs"] == 0


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------


class TestComputeStats:
    def test_basic_stats(self, analysis):
        stats = analysis._compute_stats([10.0, 20.0, 30.0])
        assert stats["mean"] == 20.0
        assert stats["median"] == 20.0
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0
        assert stats["count"] == 3

    def test_empty_values(self, analysis):
        stats = analysis._compute_stats([])
        assert stats["mean"] is None
        assert stats["count"] == 0

    def test_single_value(self, analysis):
        stats = analysis._compute_stats([42.0])
        assert stats["mean"] == 42.0
        assert stats["std"] == 0.0
        assert stats["count"] == 1


# ---------------------------------------------------------------------------
# Effect size labels
# ---------------------------------------------------------------------------


class TestEffectLabel:
    def test_large(self, analysis):
        assert analysis._effect_label(0.8) == "large"
        assert analysis._effect_label(1.5) == "large"
        assert analysis._effect_label(-0.9) == "large"

    def test_medium(self, analysis):
        assert analysis._effect_label(0.5) == "medium"
        assert analysis._effect_label(0.7) == "medium"
        assert analysis._effect_label(-0.6) == "medium"

    def test_small(self, analysis):
        assert analysis._effect_label(0.2) == "small"
        assert analysis._effect_label(0.4) == "small"
        assert analysis._effect_label(-0.3) == "small"

    def test_negligible(self, analysis):
        assert analysis._effect_label(0.0) == "negligible"
        assert analysis._effect_label(0.1) == "negligible"
        assert analysis._effect_label(-0.1) == "negligible"

    def test_infinite(self, analysis):
        assert analysis._effect_label(float("inf")) == "infinite"
        assert analysis._effect_label(float("-inf")) == "infinite"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_basic_render(self, analysis):
        report = AnalysisReport(
            project="thefuck",
            total_buggy=30,
            total_fixed=30,
            buggy_error_rate=0.1,
            fixed_error_rate=0.05,
            buggy_score_stats={
                "mean": 75.0,
                "median": 77.0,
                "std": 10.0,
                "min": 50.0,
                "max": 100.0,
                "count": 30,
            },
            fixed_score_stats={
                "mean": 82.0,
                "median": 85.0,
                "std": 8.0,
                "min": 60.0,
                "max": 100.0,
                "count": 30,
            },
            paired_results=[
                PairedResult(
                    metric="score",
                    n_pairs=25,
                    mean_delta=7.0,
                    median_delta=5.0,
                    std_delta=4.0,
                    pct_fixed_better=0.7,
                    cohens_d=1.75,
                ),
            ],
            excluded_metrics=[
                PairedResult(
                    metric="pylint_score",
                    excluded=True,
                    exclude_reason="null_rate=45% > 30%",
                ),
            ],
            total_pairs=25,
        )

        md = analysis._render_report(report)

        assert "# BugsInPy Validation Report: thefuck" in md
        assert "Buggy files annotated: 30" in md
        assert "Fixed files annotated: 30" in md
        assert "Total pairs: 25" in md
        assert "score" in md
        assert "pylint_score" in md
        assert "null_rate=45% > 30%" in md

    def test_conclusion_with_significant_metrics(self, analysis):
        report = AnalysisReport(
            project="thefuck",
            paired_results=[
                PairedResult(metric="score", cohens_d=0.9),
                PairedResult(metric="ruff_violations", cohens_d=0.3),
            ],
        )
        md = analysis._render_report(report)
        assert "2 metrics" in md
        assert "Large effects: score" in md
        assert "Small effects: ruff_violations" in md

    def test_conclusion_no_significant(self, analysis):
        report = AnalysisReport(
            project="thefuck",
            paired_results=[
                PairedResult(metric="score", cohens_d=0.1),
            ],
        )
        md = analysis._render_report(report)
        assert "No metrics show meaningful effect sizes" in md


# ---------------------------------------------------------------------------
# Numeric metrics list
# ---------------------------------------------------------------------------


class TestNumericMetrics:
    def test_score_in_list(self):
        assert "score" in _NUMERIC_METRICS

    def test_cohens_d_relevant_metrics(self):
        """Key metrics from PRP should be in the list."""
        expected = {
            "score",
            "ruff_violations",
            "cyclomatic_complexity",
            "halstead_volume",
            "maintainability_index",
        }
        assert expected.issubset(set(_NUMERIC_METRICS))


# ---------------------------------------------------------------------------
# _load_jsonl
# ---------------------------------------------------------------------------


class TestLoadJsonl:
    def test_basic(self, analysis, tmp_path):
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(
            '{"path": "a.py", "score": 80}\n{"path": "b.py", "score": 90}\n'
        )
        records = analysis._load_jsonl(jsonl)
        assert len(records) == 2
        assert records[0]["path"] == "a.py"

    def test_empty(self, analysis, tmp_path):
        jsonl = tmp_path / "empty.jsonl"
        jsonl.write_text("")
        records = analysis._load_jsonl(jsonl)
        assert records == []

    def test_blank_lines_skipped(self, analysis, tmp_path):
        jsonl = tmp_path / "blanks.jsonl"
        jsonl.write_text('{"path": "a.py"}\n\n{"path": "b.py"}\n')
        records = analysis._load_jsonl(jsonl)
        assert len(records) == 2
