"""Tests for code_reporter.py _calculate_score and _get_grade.

Scoring rules (unified with code_analyzer.py per HUA-2130-ADR):
  - Ruff violations: -2 each, capped at 30
  - Complexity >10: (cc - 10) * 5, capped at 20
  - Bandit HIGH: -15 each, capped at 30
  - Bandit MEDIUM: -5 each, capped at 15
  - Mypy errors: -1 each, capped at 10
  - Floor at 0

Grade returns descriptive labels: "A (Excellent)", "B (Good)", etc.
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
        m = FileMetrics(file_path="t.py", lint_violations=1)
        assert analyzer._calculate_score(m) == 98.0

    def test_ruff_deduction_below_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", lint_violations=10)
        assert analyzer._calculate_score(m) == 80.0

    def test_ruff_deduction_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", lint_violations=15)
        # 15 * 2 = 30, exactly at cap
        assert analyzer._calculate_score(m) == 70.0

    def test_ruff_deduction_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", lint_violations=20)
        # 20 * 2 = 40, capped at 30
        assert analyzer._calculate_score(m) == 70.0

    # --- Complexity >10: (cc - 10) * 5, capped at 20 ---

    def test_complexity_at_10_no_deduction(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=10)
        assert analyzer._calculate_score(m) == 100.0

    def test_complexity_11_deducts_5(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=11)
        # (11 - 10) * 5 = 5
        assert analyzer._calculate_score(m) == 95.0

    def test_complexity_below_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=13)
        # (13 - 10) * 5 = 15, under cap of 20
        assert analyzer._calculate_score(m) == 85.0

    def test_complexity_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=14)
        # (14 - 10) * 5 = 20, exactly at cap
        assert analyzer._calculate_score(m) == 80.0

    def test_complexity_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", max_complexity=25)
        # (25 - 10) * 5 = 75, capped at 20
        assert analyzer._calculate_score(m) == 80.0

    # --- Bandit HIGH: -15 each, capped at 30 ---

    def test_security_high_single(self, analyzer):
        m = FileMetrics(file_path="t.py", security_high=1)
        assert analyzer._calculate_score(m) == 85.0

    def test_security_high_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", security_high=2)
        assert analyzer._calculate_score(m) == 70.0

    def test_security_high_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", security_high=3)
        # 3 * 15 = 45, capped at 30
        assert analyzer._calculate_score(m) == 70.0

    # --- Bandit MEDIUM: -5 each, capped at 15 ---

    def test_security_medium_single(self, analyzer):
        m = FileMetrics(file_path="t.py", security_medium=1)
        assert analyzer._calculate_score(m) == 95.0

    def test_security_medium_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", security_medium=3)
        assert analyzer._calculate_score(m) == 85.0

    def test_security_medium_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", security_medium=5)
        # 5 * 5 = 25, capped at 15
        assert analyzer._calculate_score(m) == 85.0

    # --- Mypy errors: -1 each, capped at 10 ---

    def test_mypy_single_error(self, analyzer):
        m = FileMetrics(file_path="t.py", type_errors=1)
        assert analyzer._calculate_score(m) == 99.0

    def test_mypy_at_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", type_errors=10)
        assert analyzer._calculate_score(m) == 90.0

    def test_mypy_over_cap(self, analyzer):
        m = FileMetrics(file_path="t.py", type_errors=15)
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
            lint_violations=20,  # cap 30
            max_complexity=30,  # cap 20
            security_high=3,  # cap 30
            security_medium=5,  # cap 15
            type_errors=15,  # cap 10
        )
        # Total deductions: 30 + 20 + 30 + 15 + 10 = 105
        # 100 - 105 = -5, floored to 0
        assert analyzer._calculate_score(m) == 0.0


# ===================================================================
# _get_grade tests
# ===================================================================


class TestGetGrade:
    """Tests for code_reporter CodeAnalyzer._get_grade.

    Returns descriptive grade labels (unified per HUA-2130-ADR).
    Boundaries: 90, 80, 70, 60. Tested on both sides.
    """

    def test_grade_100(self, analyzer):
        assert analyzer._get_grade(100.0) == "A (Excellent)"

    def test_grade_at_90(self, analyzer):
        assert analyzer._get_grade(90.0) == "A (Excellent)"

    def test_grade_at_89_9(self, analyzer):
        assert analyzer._get_grade(89.9) == "B (Good)"

    def test_grade_at_80(self, analyzer):
        assert analyzer._get_grade(80.0) == "B (Good)"

    def test_grade_at_79_9(self, analyzer):
        assert analyzer._get_grade(79.9) == "C (Fair)"

    def test_grade_at_70(self, analyzer):
        assert analyzer._get_grade(70.0) == "C (Fair)"

    def test_grade_at_69_9(self, analyzer):
        assert analyzer._get_grade(69.9) == "D (Pass)"

    def test_grade_at_60(self, analyzer):
        assert analyzer._get_grade(60.0) == "D (Pass)"

    def test_grade_at_59_9(self, analyzer):
        assert analyzer._get_grade(59.9) == "F (Fail)"

    def test_grade_at_0(self, analyzer):
        assert analyzer._get_grade(0.0) == "F (Fail)"
