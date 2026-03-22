"""Tests for code_reporter.py _calculate_score and _get_grade.

Scoring rules (code_reporter.py) -- DIFFERENT from code_analyzer.py:
  - Ruff violations: -2 each, capped at 30
  - Complexity >10: (cc - 10) * 3, capped at 25  (analyzer uses *5, cap 20)
  - Bandit HIGH: -15 each, capped at 30
  - Bandit MEDIUM: -5 each, capped at 15
  - Mypy errors: -1 each, capped at 10
  - Floor at 0

Grade returns single-letter strings: "A", "B", "C", "D", "F" (no Chinese labels).
"""

import pytest

from dr_huatuo.code_reporter import CodeAnalyzer, FileMetrics


@pytest.fixture
def analyzer():
    """Create a CodeAnalyzer instance without running tool checks."""
    obj = object.__new__(CodeAnalyzer)
    obj.available_tools = {}
    return obj


# ===================================================================
# _calculate_score tests
# ===================================================================


class TestCalculateScore:
    """Tests for code_reporter CodeAnalyzer._calculate_score."""

    def test_all_zeros_score_100(self, analyzer, zero_file_metrics):
        """All metrics at zero should yield a perfect score of 100."""
        assert analyzer._calculate_score(zero_file_metrics) == 100.0

    def test_clean_metrics_score_100(self, analyzer, clean_file_metrics):
        """Clean metrics (complexity <= 10, no violations) should be 100."""
        assert analyzer._calculate_score(clean_file_metrics) == 100.0

    # --- Ruff violations: -2 each, capped at 30 ---

    def test_ruff_single_violation(self, analyzer):
        m = FileMetrics(file_path="t.py", ruff_violations=1)
        assert analyzer._calculate_score(m) == 98.0

    def test_ruff_deduction_below_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", ruff_violations=10)
        assert analyzer._calculate_score(m) == 80.0

    def test_ruff_deduction_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", ruff_violations=15)
        # 15 * 2 = 30, exactly at cap
        assert analyzer._calculate_score(m) == 70.0

    def test_ruff_deduction_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", ruff_violations=20)
        # 20 * 2 = 40, capped at 30
        assert analyzer._calculate_score(m) == 70.0

    # --- Complexity >10: (cc - 10) * 3, capped at 25 ---

    def test_complexity_at_10_no_deduction(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=10)
        assert analyzer._calculate_score(m) == 100.0

    def test_complexity_11_deducts_3(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=11)
        # (11 - 10) * 3 = 3
        assert analyzer._calculate_score(m) == 97.0

    def test_complexity_below_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=15)
        # (15 - 10) * 3 = 15, under cap of 25
        assert analyzer._calculate_score(m) == 85.0

    def test_complexity_near_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=18)
        # (18 - 10) * 3 = 24, under cap of 25
        assert analyzer._calculate_score(m) == 76.0

    def test_complexity_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=25)
        # (25 - 10) * 3 = 45, capped at 25
        assert analyzer._calculate_score(m) == 75.0

    def test_complexity_exact_cap_boundary(self, analyzer):
        """Find the exact cc where the cap kicks in: (cc-10)*3 = 25 is not
        an integer boundary, so the first cc that would exceed 25 is cc=19
        where (19-10)*3=27 > 25, capped to 25."""
        m = FileMetrics(file_path="t.py", max_complexity=19)
        # (19 - 10) * 3 = 27, capped at 25
        assert analyzer._calculate_score(m) == 75.0

    # --- Bandit HIGH: -15 each, capped at 30 ---

    def test_bandit_high_single(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_high=1)
        assert analyzer._calculate_score(m) == 85.0

    def test_bandit_high_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_high=2)
        assert analyzer._calculate_score(m) == 70.0

    def test_bandit_high_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_high=3)
        # 3 * 15 = 45, capped at 30
        assert analyzer._calculate_score(m) == 70.0

    # --- Bandit MEDIUM: -5 each, capped at 15 ---

    def test_bandit_medium_single(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_medium=1)
        assert analyzer._calculate_score(m) == 95.0

    def test_bandit_medium_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_medium=3)
        assert analyzer._calculate_score(m) == 85.0

    def test_bandit_medium_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", bandit_medium=5)
        # 5 * 5 = 25, capped at 15
        assert analyzer._calculate_score(m) == 85.0

    # --- Mypy errors: -1 each, capped at 10 ---

    def test_mypy_single_error(self, analyzer):
        m = FileMetrics(file_path="t.py", mypy_errors=1)
        assert analyzer._calculate_score(m) == 99.0

    def test_mypy_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", mypy_errors=10)
        assert analyzer._calculate_score(m) == 90.0

    def test_mypy_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", mypy_errors=15)
        assert analyzer._calculate_score(m) == 90.0

    # --- Floor at 0: all caps hit simultaneously ---

    def test_score_floor_at_zero(self, analyzer, bad_file_metrics):
        """Score should never go below 0 even when all caps are maxed."""
        score = analyzer._calculate_score(bad_file_metrics)
        assert score >= 0

    def test_score_floor_all_caps_maxed(self, analyzer):
        """Explicitly max all dimensions to exceed 100 deductions."""
        m = FileMetrics(
            file_path="t.py",
            ruff_violations=20,  # cap 30
            max_complexity=30,  # cap 25
            bandit_high=3,  # cap 30
            bandit_medium=5,  # cap 15
            mypy_errors=15,  # cap 10
        )
        # Total deductions: 30 + 25 + 30 + 15 + 10 = 110
        # 100 - 110 = -10, floored to 0
        assert analyzer._calculate_score(m) == 0.0


# ===================================================================
# _get_grade tests
# ===================================================================


class TestGetGrade:
    """Tests for code_reporter CodeAnalyzer._get_grade.

    Returns single-letter grade strings (no Chinese labels).
    Boundaries: 90, 80, 70, 60. Tested on both sides.
    """

    def test_grade_100(self, analyzer):
        assert analyzer._get_grade(100.0) == "A"

    def test_grade_at_90(self, analyzer):
        assert analyzer._get_grade(90.0) == "A"

    def test_grade_at_89_9(self, analyzer):
        assert analyzer._get_grade(89.9) == "B"

    def test_grade_at_80(self, analyzer):
        assert analyzer._get_grade(80.0) == "B"

    def test_grade_at_79_9(self, analyzer):
        assert analyzer._get_grade(79.9) == "C"

    def test_grade_at_70(self, analyzer):
        assert analyzer._get_grade(70.0) == "C"

    def test_grade_at_69_9(self, analyzer):
        assert analyzer._get_grade(69.9) == "D"

    def test_grade_at_60(self, analyzer):
        assert analyzer._get_grade(60.0) == "D"

    def test_grade_at_59_9(self, analyzer):
        assert analyzer._get_grade(59.9) == "F"

    def test_grade_at_0(self, analyzer):
        assert analyzer._get_grade(0.0) == "F"
