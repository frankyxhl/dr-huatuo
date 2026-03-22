"""Tests for scoring_optimizer.py.

Covers: pair loading, path-based pairing reconstruction, pair-correct rate
computation, parameterized scoring, baseline weights, optimization bounds,
OptimizationResult dataclass, CLI flag parsing, and LOPO cross-validation.

TDD-first per COR-1500 for HUA-2118-PRP.
"""

import json
import re

import pytest

from scoring_optimizer import (
    BASELINE_WEIGHTS,
    BOUNDS,
    OptimizationResult,
    ScoringOptimizer,
    _calculate_score_with_params,
    _pair_correct_rate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PAIR_REGEX = re.compile(
    r".*/(?P<variant>buggy|fixed)/bug_(?P<bug_id>\d+)/(?P<affected_file>.+)$"
)


def _make_record(path, **overrides):
    """Build a minimal annotated record for testing."""
    record = {
        "path": path,
        "score": 80.0,
        "ruff_violations": 2,
        "bandit_high": 0,
        "bandit_medium": 0,
        "mypy_errors": 1,
        "cyclomatic_complexity": 5,
        "error_type": None,
    }
    record.update(overrides)
    return record


def _write_jsonl(path, records):
    """Write records to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def paired_data(tmp_path):
    """Create a small paired dataset in tmp_path/thefuck/.

    3 pairs where fixed should generally score higher with good weights:
      - pair 1: fixed has fewer violations
      - pair 2: fixed has lower complexity
      - pair 3: fixed has fewer mypy errors
    """
    project_dir = tmp_path / "thefuck"
    project_dir.mkdir()

    buggy_records = [
        _make_record(
            "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py",
            ruff_violations=5,
            cyclomatic_complexity=12,
            bandit_high=1,
            bandit_medium=0,
            mypy_errors=3,
        ),
        _make_record(
            "data/bugsinpy/thefuck/buggy/bug_2/thefuck/app.py",
            ruff_violations=2,
            cyclomatic_complexity=15,
            bandit_high=0,
            bandit_medium=2,
            mypy_errors=1,
        ),
        _make_record(
            "data/bugsinpy/thefuck/buggy/bug_3/thefuck/shell.py",
            ruff_violations=1,
            cyclomatic_complexity=8,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=5,
        ),
    ]

    fixed_records = [
        _make_record(
            "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py",
            ruff_violations=1,
            cyclomatic_complexity=8,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=0,
        ),
        _make_record(
            "data/bugsinpy/thefuck/fixed/bug_2/thefuck/app.py",
            ruff_violations=0,
            cyclomatic_complexity=7,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=0,
        ),
        _make_record(
            "data/bugsinpy/thefuck/fixed/bug_3/thefuck/shell.py",
            ruff_violations=0,
            cyclomatic_complexity=6,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=1,
        ),
    ]

    _write_jsonl(project_dir / "buggy_annotated.jsonl", buggy_records)
    _write_jsonl(project_dir / "fixed_annotated.jsonl", fixed_records)

    return tmp_path


# ---------------------------------------------------------------------------
# OptimizationResult dataclass
# ---------------------------------------------------------------------------


class TestOptimizationResult:
    def test_defaults(self):
        r = OptimizationResult(
            current_weights={},
            current_train_pcr=0.5,
            current_test_pcr=None,
            optimized_weights={},
            optimized_train_pcr=0.7,
            optimized_test_pcr=None,
            improvement_train=20.0,
            improvement_test=None,
            scipy_result=None,
        )
        assert r.current_train_pcr == 0.5
        assert r.optimized_train_pcr == 0.7
        assert r.improvement_train == 20.0
        assert r.improvement_test is None
        assert r.scipy_result is None

    def test_with_test_set(self):
        r = OptimizationResult(
            current_weights={},
            current_train_pcr=0.5,
            current_test_pcr=0.48,
            optimized_weights={},
            optimized_train_pcr=0.7,
            optimized_test_pcr=0.65,
            improvement_train=20.0,
            improvement_test=17.0,
            scipy_result=None,
        )
        assert r.current_test_pcr == 0.48
        assert r.optimized_test_pcr == 0.65
        assert r.improvement_test == 17.0


# ---------------------------------------------------------------------------
# Baseline weights
# ---------------------------------------------------------------------------


class TestBaselineWeights:
    def test_baseline_keys(self):
        """Baseline weights should have the 11 expected parameters."""
        expected_keys = {
            "ruff_weight",
            "ruff_cap",
            "complexity_threshold",
            "complexity_weight",
            "complexity_cap",
            "bandit_high_weight",
            "bandit_high_cap",
            "bandit_medium_weight",
            "bandit_medium_cap",
            "mypy_weight",
            "mypy_cap",
        }
        assert set(BASELINE_WEIGHTS.keys()) == expected_keys

    def test_baseline_matches_annotator(self):
        """Baseline should match dataset_annotator._calculate_score defaults."""
        assert BASELINE_WEIGHTS["ruff_weight"] == 2
        assert BASELINE_WEIGHTS["ruff_cap"] == 30
        assert BASELINE_WEIGHTS["complexity_threshold"] == 10
        assert BASELINE_WEIGHTS["complexity_weight"] == 5
        assert BASELINE_WEIGHTS["complexity_cap"] == 20
        assert BASELINE_WEIGHTS["bandit_high_weight"] == 15
        assert BASELINE_WEIGHTS["bandit_high_cap"] == 30
        assert BASELINE_WEIGHTS["bandit_medium_weight"] == 5
        assert BASELINE_WEIGHTS["bandit_medium_cap"] == 15
        assert BASELINE_WEIGHTS["mypy_weight"] == 1
        assert BASELINE_WEIGHTS["mypy_cap"] == 10


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


class TestBounds:
    def test_bounds_length(self):
        """11 parameters -> 11 bounds."""
        assert len(BOUNDS) == 11

    def test_bounds_are_tuples(self):
        for b in BOUNDS:
            assert isinstance(b, tuple)
            assert len(b) == 2
            assert b[0] < b[1]

    def test_baseline_within_bounds(self):
        """Baseline weights should be within bounds."""
        param_order = [
            "ruff_weight",
            "ruff_cap",
            "complexity_threshold",
            "complexity_weight",
            "complexity_cap",
            "bandit_high_weight",
            "bandit_high_cap",
            "bandit_medium_weight",
            "bandit_medium_cap",
            "mypy_weight",
            "mypy_cap",
        ]
        for i, key in enumerate(param_order):
            val = BASELINE_WEIGHTS[key]
            lo, hi = BOUNDS[i]
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"


# ---------------------------------------------------------------------------
# _calculate_score_with_params
# ---------------------------------------------------------------------------


class TestCalculateScoreWithParams:
    def test_perfect_score(self):
        """No violations should yield 100."""
        metrics = {
            "ruff_violations": 0,
            "cyclomatic_complexity": 0,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 0,
        }
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 100.0

    def test_ruff_deduction(self):
        """Ruff violations should deduct weight per violation, capped."""
        metrics = {
            "ruff_violations": 5,
            "cyclomatic_complexity": 0,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 0,
        }
        # weight=3, cap=12 -> deduction = min(5*3, 12) = 12
        params = (3, 12, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 88.0

    def test_complexity_threshold(self):
        """Complexity below threshold should not deduct."""
        metrics = {
            "ruff_violations": 0,
            "cyclomatic_complexity": 8,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 0,
        }
        # threshold=10, cc=8 -> no deduction
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 100.0

    def test_complexity_above_threshold(self):
        """Complexity above threshold should deduct."""
        metrics = {
            "ruff_violations": 0,
            "cyclomatic_complexity": 15,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 0,
        }
        # threshold=10, weight=5, cap=20 -> deduction = min((15-10)*5, 20) = 20
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 80.0

    def test_floor_at_zero(self):
        """Score should never go below 0."""
        metrics = {
            "ruff_violations": 100,
            "cyclomatic_complexity": 50,
            "bandit_high": 10,
            "bandit_medium": 10,
            "mypy_errors": 100,
        }
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 0.0

    def test_none_metrics_treated_as_zero(self):
        """None metric values should be treated as 0."""
        metrics = {
            "ruff_violations": None,
            "cyclomatic_complexity": None,
            "bandit_high": None,
            "bandit_medium": None,
            "mypy_errors": None,
        }
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _calculate_score_with_params(metrics, params) == 100.0

    def test_baseline_matches_annotator(self):
        """With baseline params, score should match annotator."""
        from dataset_annotator import _calculate_score

        metrics = {
            "ruff_violations": 5,
            "cyclomatic_complexity": 15,
            "bandit_high": 1,
            "bandit_medium": 2,
            "mypy_errors": 3,
        }
        baseline_params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        expected = _calculate_score(
            ruff_violations=5,
            cyclomatic_complexity=15,
            bandit_high=1,
            bandit_medium=2,
            mypy_errors=3,
        )
        assert _calculate_score_with_params(metrics, baseline_params) == expected


# ---------------------------------------------------------------------------
# _pair_correct_rate
# ---------------------------------------------------------------------------


class TestPairCorrectRate:
    def test_all_correct(self):
        """When fixed always scores higher, PCR should be 1.0."""
        pairs = [
            (
                {
                    "ruff_violations": 5,
                    "cyclomatic_complexity": 15,
                    "bandit_high": 1,
                    "bandit_medium": 1,
                    "mypy_errors": 3,
                },
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
            ),
        ]
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _pair_correct_rate(params, pairs) == 1.0

    def test_none_correct(self):
        """When buggy always scores higher, PCR should be 0.0."""
        pairs = [
            (
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
                {
                    "ruff_violations": 5,
                    "cyclomatic_complexity": 15,
                    "bandit_high": 1,
                    "bandit_medium": 1,
                    "mypy_errors": 3,
                },
            ),
        ]
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _pair_correct_rate(params, pairs) == 0.0

    def test_tied_scores_not_correct(self):
        """Tied scores (fixed == buggy) should not count as correct."""
        pairs = [
            (
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
            ),
        ]
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _pair_correct_rate(params, pairs) == 0.0

    def test_mixed(self):
        """Mixed results: 2 out of 3 correct -> PCR ~0.667."""
        pairs = [
            (
                {
                    "ruff_violations": 5,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
            ),
            (
                {
                    "ruff_violations": 3,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
            ),
            # This pair is wrong direction: fixed has MORE violations
            (
                {
                    "ruff_violations": 0,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
                {
                    "ruff_violations": 5,
                    "cyclomatic_complexity": 5,
                    "bandit_high": 0,
                    "bandit_medium": 0,
                    "mypy_errors": 0,
                },
            ),
        ]
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _pair_correct_rate(params, pairs) == pytest.approx(2 / 3)

    def test_empty_pairs(self):
        """Empty pairs should return 0.0."""
        params = (2, 30, 10, 5, 20, 15, 30, 5, 15, 1, 10)
        assert _pair_correct_rate(params, []) == 0.0


# ---------------------------------------------------------------------------
# ScoringOptimizer: pair loading
# ---------------------------------------------------------------------------


class TestLoadPairs:
    def test_load_from_project_dir(self, paired_data):
        """Should load and pair records from buggy/fixed JSONL files."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        assert len(optimizer.train_pairs) == 3

    def test_pair_alignment(self, paired_data):
        """Each pair should have same (bug_id, affected_file)."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        for buggy, fixed in optimizer.train_pairs:
            buggy_m = _PAIR_REGEX.search(buggy["path"])
            fixed_m = _PAIR_REGEX.search(fixed["path"])
            assert buggy_m is not None
            assert fixed_m is not None
            assert buggy_m.group("bug_id") == fixed_m.group("bug_id")
            assert buggy_m.group("affected_file") == fixed_m.group("affected_file")

    def test_error_records_excluded(self, paired_data):
        """Records with error_type should be excluded from pairs."""
        # Add an error record to the buggy file
        buggy_path = paired_data / "thefuck" / "buggy_annotated.jsonl"
        with open(buggy_path, "a") as f:
            err_record = _make_record(
                "data/bugsinpy/thefuck/buggy/bug_99/thefuck/broken.py",
                error_type="syntax_error",
            )
            f.write(json.dumps(err_record) + "\n")
        # Add corresponding fixed record
        fixed_path = paired_data / "thefuck" / "fixed_annotated.jsonl"
        with open(fixed_path, "a") as f:
            ok_record = _make_record(
                "data/bugsinpy/thefuck/fixed/bug_99/thefuck/broken.py",
            )
            f.write(json.dumps(ok_record) + "\n")

        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        # Should still be 3 (the error pair is excluded)
        assert len(optimizer.train_pairs) == 3

    def test_separate_train_test(self, paired_data):
        """Test projects should be loaded into test_pairs."""
        # Create a second project
        proj2 = paired_data / "luigi"
        proj2.mkdir()
        _write_jsonl(
            proj2 / "buggy_annotated.jsonl",
            [
                _make_record(
                    "data/bugsinpy/luigi/buggy/bug_1/luigi/task.py",
                    ruff_violations=3,
                    cyclomatic_complexity=10,
                ),
            ],
        )
        _write_jsonl(
            proj2 / "fixed_annotated.jsonl",
            [
                _make_record(
                    "data/bugsinpy/luigi/fixed/bug_1/luigi/task.py",
                    ruff_violations=0,
                    cyclomatic_complexity=5,
                ),
            ],
        )

        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
            test_projects=["luigi"],
        )
        assert len(optimizer.train_pairs) == 3
        assert len(optimizer.test_pairs) == 1


# ---------------------------------------------------------------------------
# ScoringOptimizer: baseline computation
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_baseline_pcr(self, paired_data):
        """Baseline PCR should be computed on train pairs."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        result = optimizer.optimize(baseline_only=True)
        assert 0.0 <= result.current_train_pcr <= 1.0
        # optimized should equal current in baseline_only mode
        assert result.optimized_train_pcr == result.current_train_pcr
        assert result.improvement_train == 0.0


# ---------------------------------------------------------------------------
# ScoringOptimizer: optimization
# ---------------------------------------------------------------------------


class TestOptimize:
    def test_optimization_improves_or_equals(self, paired_data):
        """Optimized PCR should be >= baseline PCR on train set."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        result = optimizer.optimize()
        assert result.optimized_train_pcr >= result.current_train_pcr

    def test_optimization_result_structure(self, paired_data):
        """Result should have all required fields."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        result = optimizer.optimize()

        assert isinstance(result.current_weights, dict)
        assert isinstance(result.optimized_weights, dict)
        assert isinstance(result.current_train_pcr, float)
        assert isinstance(result.optimized_train_pcr, float)
        assert isinstance(result.improvement_train, float)
        assert result.scipy_result is not None

    def test_optimized_weights_has_correct_keys(self, paired_data):
        """Optimized weights should have the same keys as baseline."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        result = optimizer.optimize()
        assert set(result.optimized_weights.keys()) == set(BASELINE_WEIGHTS.keys())

    def test_optimized_weights_within_bounds(self, paired_data):
        """Optimized weights should be within the defined bounds."""
        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
        )
        result = optimizer.optimize()
        param_order = [
            "ruff_weight",
            "ruff_cap",
            "complexity_threshold",
            "complexity_weight",
            "complexity_cap",
            "bandit_high_weight",
            "bandit_high_cap",
            "bandit_medium_weight",
            "bandit_medium_cap",
            "mypy_weight",
            "mypy_cap",
        ]
        for i, key in enumerate(param_order):
            val = result.optimized_weights[key]
            lo, hi = BOUNDS[i]
            assert lo <= val <= hi, f"{key}={val} not in [{lo}, {hi}]"

    def test_with_test_set(self, paired_data):
        """When test projects provided, result should have test PCR."""
        # Create a test project
        proj2 = paired_data / "luigi"
        proj2.mkdir()
        _write_jsonl(
            proj2 / "buggy_annotated.jsonl",
            [
                _make_record(
                    "data/bugsinpy/luigi/buggy/bug_1/luigi/task.py",
                    ruff_violations=4,
                    cyclomatic_complexity=12,
                ),
            ],
        )
        _write_jsonl(
            proj2 / "fixed_annotated.jsonl",
            [
                _make_record(
                    "data/bugsinpy/luigi/fixed/bug_1/luigi/task.py",
                    ruff_violations=1,
                    cyclomatic_complexity=6,
                ),
            ],
        )

        optimizer = ScoringOptimizer(
            data_root=str(paired_data),
            train_projects=["thefuck"],
            test_projects=["luigi"],
        )
        result = optimizer.optimize()

        assert result.current_test_pcr is not None
        assert result.optimized_test_pcr is not None
        assert result.improvement_test is not None


# ---------------------------------------------------------------------------
# CLI argument parsing (import-time check)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_module_has_main_guard(self):
        """scoring_optimizer.py should have if __name__ == '__main__'."""
        import scoring_optimizer

        source = open(scoring_optimizer.__file__).read()
        assert (
            'if __name__ == "__main__"' in source
            or "if __name__ == '__main__'" in source
        )
