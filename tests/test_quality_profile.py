"""Tests for quality_profile.py — TDD RED/GREEN/REFACTOR cycles.

Tests cover:
- DimensionResult and QualityProfile dataclasses
- Maintainability dimension (MI thresholds A/B/C/D)
- Complexity dimension (cognitive + nesting, worst-of logic)
- Code Style dimension (ruff + pylint, worst-of logic)
- Documentation dimension (docstring + comment density, edge cases)
- Security dimension (PASS/WARN/FAIL gate)
- Null/None handling for all dimensions
- profile_file() integration
- Summary string format
- Limiting metric correctness
"""

from quality_profile import (
    QualityProfile,
    _rate_code_style,
    _rate_complexity,
    _rate_documentation,
    _rate_maintainability,
    _rate_security,
    profile_file,
)

# QualityProfile used in isinstance checks; ruff may flag as unused but it is needed.


# ===================================================================
# Dimension 1: Maintainability (MI only)
# ===================================================================


class TestRateMaintainability:
    """MI thresholds: A >= 40, B >= 20 < 40, C >= 10 < 20, D < 10."""

    def test_a_high(self):
        r = _rate_maintainability(80.0)
        assert r.rating == "A"
        assert r.name == "maintainability"

    def test_a_boundary(self):
        r = _rate_maintainability(40.0)
        assert r.rating == "A"

    def test_b_just_below_a(self):
        r = _rate_maintainability(39.9)
        assert r.rating == "B"

    def test_b_boundary(self):
        r = _rate_maintainability(20.0)
        assert r.rating == "B"

    def test_c_just_below_b(self):
        r = _rate_maintainability(19.9)
        assert r.rating == "C"

    def test_c_boundary(self):
        r = _rate_maintainability(10.0)
        assert r.rating == "C"

    def test_d_just_below_c(self):
        r = _rate_maintainability(9.9)
        assert r.rating == "D"

    def test_d_zero(self):
        r = _rate_maintainability(0.0)
        assert r.rating == "D"

    def test_null_returns_none(self):
        r = _rate_maintainability(None)
        assert r.rating is None
        assert r.limiting_metric is None

    def test_detail_contains_mi(self):
        r = _rate_maintainability(52.3)
        assert r.detail == {"maintainability_index": "A"}

    def test_limiting_metric_is_mi(self):
        r = _rate_maintainability(15.0)
        assert r.limiting_metric == "maintainability_index"


# ===================================================================
# Dimension 2: Complexity (worst of cognitive + nesting)
# ===================================================================


class TestRateComplexity:
    """Cognitive: A<=5, B>5<=15, C>15<=25, D>25.
    Nesting: A<=2, B=3, C=4-5, D>=6.
    Rating = worst of the two.
    """

    def test_both_a(self):
        r = _rate_complexity(cognitive=3, nesting=1)
        assert r.rating == "A"

    def test_cognitive_a_nesting_a_boundary(self):
        r = _rate_complexity(cognitive=5, nesting=2)
        assert r.rating == "A"

    def test_cognitive_b(self):
        r = _rate_complexity(cognitive=10, nesting=1)
        assert r.rating == "B"
        assert r.limiting_metric == "cognitive_complexity"

    def test_cognitive_b_boundary(self):
        r = _rate_complexity(cognitive=15, nesting=2)
        assert r.rating == "B"
        assert r.limiting_metric == "cognitive_complexity"

    def test_nesting_b(self):
        r = _rate_complexity(cognitive=3, nesting=3)
        assert r.rating == "B"
        assert r.limiting_metric == "max_nesting_depth"

    def test_cognitive_c(self):
        r = _rate_complexity(cognitive=20, nesting=2)
        assert r.rating == "C"
        assert r.limiting_metric == "cognitive_complexity"

    def test_cognitive_c_boundary(self):
        r = _rate_complexity(cognitive=25, nesting=2)
        assert r.rating == "C"

    def test_nesting_c_four(self):
        r = _rate_complexity(cognitive=3, nesting=4)
        assert r.rating == "C"
        assert r.limiting_metric == "max_nesting_depth"

    def test_nesting_c_five(self):
        r = _rate_complexity(cognitive=3, nesting=5)
        assert r.rating == "C"

    def test_cognitive_d(self):
        r = _rate_complexity(cognitive=30, nesting=2)
        assert r.rating == "D"
        assert r.limiting_metric == "cognitive_complexity"

    def test_nesting_d(self):
        r = _rate_complexity(cognitive=3, nesting=6)
        assert r.rating == "D"
        assert r.limiting_metric == "max_nesting_depth"

    def test_worst_of_cognitive_d_nesting_a(self):
        """Cognitive D is worse than nesting A -> dimension is D."""
        r = _rate_complexity(cognitive=30, nesting=1)
        assert r.rating == "D"
        assert r.limiting_metric == "cognitive_complexity"

    def test_worst_of_nesting_d_cognitive_a(self):
        """Nesting D is worse than cognitive A -> dimension is D."""
        r = _rate_complexity(cognitive=3, nesting=7)
        assert r.rating == "D"
        assert r.limiting_metric == "max_nesting_depth"

    def test_both_null(self):
        r = _rate_complexity(cognitive=None, nesting=None)
        assert r.rating is None

    def test_cognitive_null_nesting_present(self):
        r = _rate_complexity(cognitive=None, nesting=3)
        assert r.rating == "B"
        assert r.limiting_metric == "max_nesting_depth"

    def test_nesting_null_cognitive_present(self):
        r = _rate_complexity(cognitive=20, nesting=None)
        assert r.rating == "C"
        assert r.limiting_metric == "cognitive_complexity"

    def test_detail_shows_both(self):
        r = _rate_complexity(cognitive=10, nesting=4)
        assert r.detail == {"cognitive_complexity": "B", "max_nesting_depth": "C"}
        assert r.rating == "C"  # worst of B and C


# ===================================================================
# Dimension 3: Code Style (worst of ruff + pylint)
# ===================================================================


class TestRateCodeStyle:
    """Ruff: A=0, B=1-3, C=4-10, D>10.
    Pylint: A>=9, B>=7<9, C>=5<7, D<5.
    Rating = worst of the two.
    """

    def test_both_a(self):
        r = _rate_code_style(ruff=0, pylint=9.5)
        assert r.rating == "A"

    def test_ruff_b(self):
        r = _rate_code_style(ruff=2, pylint=9.5)
        assert r.rating == "B"
        assert r.limiting_metric == "ruff_violations"

    def test_ruff_b_boundary(self):
        r = _rate_code_style(ruff=3, pylint=9.5)
        assert r.rating == "B"

    def test_ruff_c(self):
        r = _rate_code_style(ruff=7, pylint=9.5)
        assert r.rating == "C"

    def test_ruff_c_boundary(self):
        r = _rate_code_style(ruff=10, pylint=9.5)
        assert r.rating == "C"

    def test_ruff_d(self):
        r = _rate_code_style(ruff=15, pylint=9.5)
        assert r.rating == "D"

    def test_pylint_a_boundary(self):
        r = _rate_code_style(ruff=0, pylint=9.0)
        assert r.rating == "A"

    def test_pylint_b(self):
        r = _rate_code_style(ruff=0, pylint=8.0)
        assert r.rating == "B"
        assert r.limiting_metric == "pylint_score"

    def test_pylint_b_boundary(self):
        r = _rate_code_style(ruff=0, pylint=7.0)
        assert r.rating == "B"

    def test_pylint_c(self):
        r = _rate_code_style(ruff=0, pylint=6.0)
        assert r.rating == "C"
        assert r.limiting_metric == "pylint_score"

    def test_pylint_c_boundary(self):
        r = _rate_code_style(ruff=0, pylint=5.0)
        assert r.rating == "C"

    def test_pylint_d(self):
        r = _rate_code_style(ruff=0, pylint=3.0)
        assert r.rating == "D"
        assert r.limiting_metric == "pylint_score"

    def test_worst_of_ruff_d_pylint_a(self):
        r = _rate_code_style(ruff=15, pylint=9.5)
        assert r.rating == "D"
        assert r.limiting_metric == "ruff_violations"

    def test_worst_of_pylint_d_ruff_a(self):
        r = _rate_code_style(ruff=0, pylint=2.0)
        assert r.rating == "D"
        assert r.limiting_metric == "pylint_score"

    def test_both_null(self):
        r = _rate_code_style(ruff=None, pylint=None)
        assert r.rating is None

    def test_ruff_null_pylint_present(self):
        r = _rate_code_style(ruff=None, pylint=8.0)
        assert r.rating == "B"

    def test_pylint_null_ruff_present(self):
        r = _rate_code_style(ruff=5, pylint=None)
        assert r.rating == "C"

    def test_detail_shows_both(self):
        r = _rate_code_style(ruff=2, pylint=6.0)
        assert r.detail == {"ruff_violations": "B", "pylint_score": "C"}


# ===================================================================
# Dimension 4: Documentation (worst of docstring + comment density)
# ===================================================================


class TestRateDocumentation:
    """Docstring: A>=0.80, B>=0.50<0.80, C>=0.20<0.50, D<0.20.
    Comment: A>=0.10<=0.30, B=(>=0.05<0.10)or(>0.30<=0.40),
             C>=0.01<0.05, D<0.01 or >0.40.
    Edge: function_count=0 -> exclude docstring; loc=0 -> exclude comment.
    """

    def test_both_a(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.15, function_count=10, loc=100
        )
        assert r.rating == "A"

    def test_docstring_a_boundary(self):
        r = _rate_documentation(
            docstring_d=0.80, comment_d=0.15, function_count=10, loc=100
        )
        assert r.rating == "A"

    def test_docstring_b(self):
        r = _rate_documentation(
            docstring_d=0.60, comment_d=0.15, function_count=10, loc=100
        )
        assert r.rating == "B"
        assert r.limiting_metric == "docstring_density"

    def test_docstring_c(self):
        r = _rate_documentation(
            docstring_d=0.30, comment_d=0.15, function_count=10, loc=100
        )
        assert r.rating == "C"
        assert r.limiting_metric == "docstring_density"

    def test_docstring_d(self):
        r = _rate_documentation(
            docstring_d=0.10, comment_d=0.15, function_count=10, loc=100
        )
        assert r.rating == "D"
        assert r.limiting_metric == "docstring_density"

    def test_comment_a_low_boundary(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.10, function_count=10, loc=100
        )
        assert r.rating == "A"

    def test_comment_a_high_boundary(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.30, function_count=10, loc=100
        )
        assert r.rating == "A"

    def test_comment_b_low_range(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.07, function_count=10, loc=100
        )
        assert r.rating == "B"
        assert r.limiting_metric == "comment_density"

    def test_comment_b_high_range(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.35, function_count=10, loc=100
        )
        assert r.rating == "B"
        assert r.limiting_metric == "comment_density"

    def test_comment_c(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.03, function_count=10, loc=100
        )
        assert r.rating == "C"
        assert r.limiting_metric == "comment_density"

    def test_comment_d_low(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.005, function_count=10, loc=100
        )
        assert r.rating == "D"
        assert r.limiting_metric == "comment_density"

    def test_comment_d_high(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.50, function_count=10, loc=100
        )
        assert r.rating == "D"
        assert r.limiting_metric == "comment_density"

    def test_comment_d_zero(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.0, function_count=10, loc=100
        )
        assert r.rating == "D"
        assert r.limiting_metric == "comment_density"

    def test_function_count_zero_excludes_docstring(self):
        """function_count=0 -> docstring excluded, rating based on comment only."""
        r = _rate_documentation(
            docstring_d=0.0, comment_d=0.15, function_count=0, loc=100
        )
        assert r.rating == "A"
        # docstring_density should not appear in detail
        assert "docstring_density" not in r.detail

    def test_loc_zero_excludes_comment(self):
        """loc=0 -> comment excluded. With no docstring metric, dimension = N/A."""
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.0, function_count=0, loc=0
        )
        assert r.rating is None  # N/A

    def test_both_null(self):
        r = _rate_documentation(
            docstring_d=None, comment_d=None, function_count=None, loc=None
        )
        assert r.rating is None

    def test_docstring_null_comment_present(self):
        r = _rate_documentation(
            docstring_d=None, comment_d=0.15, function_count=None, loc=100
        )
        assert r.rating == "A"

    def test_worst_of_both(self):
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.03, function_count=10, loc=100
        )
        assert r.rating == "C"
        assert r.limiting_metric == "comment_density"

    def test_comment_b_boundary_0_05(self):
        """comment_density=0.05 should be B (>=0.05 and <0.10)."""
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.05, function_count=10, loc=100
        )
        assert r.rating == "B"
        assert r.limiting_metric == "comment_density"

    def test_comment_c_boundary_0_01(self):
        """comment_density=0.01 should be C (>=0.01 and <0.05)."""
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.01, function_count=10, loc=100
        )
        assert r.rating == "C"
        assert r.limiting_metric == "comment_density"

    def test_comment_b_boundary_0_40(self):
        """comment_density=0.40 should be B (>0.30 and <=0.40)."""
        r = _rate_documentation(
            docstring_d=0.90, comment_d=0.40, function_count=10, loc=100
        )
        assert r.rating == "B"
        assert r.limiting_metric == "comment_density"


# ===================================================================
# Dimension 5: Security (PASS/WARN/FAIL)
# ===================================================================


class TestRateSecurity:
    """PASS: high=0 AND medium<=2.
    WARN: high=0 AND medium>2.
    FAIL: high>=1.
    """

    def test_pass_zero_all(self):
        r = _rate_security(bandit_high=0, bandit_medium=0)
        assert r.rating == "PASS"

    def test_pass_medium_at_limit(self):
        r = _rate_security(bandit_high=0, bandit_medium=2)
        assert r.rating == "PASS"

    def test_warn_medium_above_limit(self):
        r = _rate_security(bandit_high=0, bandit_medium=3)
        assert r.rating == "WARN"

    def test_warn_medium_high(self):
        r = _rate_security(bandit_high=0, bandit_medium=10)
        assert r.rating == "WARN"

    def test_fail_one_high(self):
        r = _rate_security(bandit_high=1, bandit_medium=0)
        assert r.rating == "FAIL"

    def test_fail_high_with_medium(self):
        r = _rate_security(bandit_high=2, bandit_medium=5)
        assert r.rating == "FAIL"

    def test_both_null(self):
        r = _rate_security(bandit_high=None, bandit_medium=None)
        assert r.rating is None

    def test_high_null_medium_present(self):
        """If high is null but medium present, cannot determine security."""
        r = _rate_security(bandit_high=None, bandit_medium=3)
        assert r.rating is None

    def test_medium_null_high_zero(self):
        """If medium is null but high=0, cannot determine fully."""
        r = _rate_security(bandit_high=0, bandit_medium=None)
        assert r.rating is None

    def test_medium_null_high_positive(self):
        """If high>=1, FAIL regardless of medium."""
        r = _rate_security(bandit_high=1, bandit_medium=None)
        assert r.rating == "FAIL"

    def test_detail_contains_values(self):
        r = _rate_security(bandit_high=0, bandit_medium=1)
        assert r.detail == {"bandit_high": 0, "bandit_medium": 1}

    def test_security_has_no_limiting_metric_on_pass(self):
        r = _rate_security(bandit_high=0, bandit_medium=0)
        assert r.limiting_metric is None

    def test_security_limiting_metric_on_fail(self):
        r = _rate_security(bandit_high=1, bandit_medium=0)
        assert r.limiting_metric == "bandit_high"

    def test_security_limiting_metric_on_warn(self):
        r = _rate_security(bandit_high=0, bandit_medium=5)
        assert r.limiting_metric == "bandit_medium"


# ===================================================================
# profile_file() integration
# ===================================================================


class TestProfileFile:
    """Test profile_file() with full annotator metric dicts."""

    def test_all_excellent(self):
        metrics = {
            "maintainability_index": 50.0,
            "cognitive_complexity": 3,
            "max_nesting_depth": 1,
            "ruff_violations": 0,
            "pylint_score": 9.5,
            "docstring_density": 0.90,
            "comment_density": 0.15,
            "function_count": 10,
            "loc": 100,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 0,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert isinstance(qp, QualityProfile)
        assert qp.maintainability.rating == "A"
        assert qp.complexity.rating == "A"
        assert qp.code_style.rating == "A"
        assert qp.documentation.rating == "A"
        assert qp.security.rating == "PASS"
        assert qp.mypy_errors == 0
        assert qp.mypy_env_sensitive is False
        assert "M:A" in qp.summary
        assert "Sec:PASS" in qp.summary

    def test_all_worst(self):
        metrics = {
            "maintainability_index": 5.0,
            "cognitive_complexity": 30,
            "max_nesting_depth": 8,
            "ruff_violations": 20,
            "pylint_score": 2.0,
            "docstring_density": 0.05,
            "comment_density": 0.50,
            "function_count": 10,
            "loc": 100,
            "bandit_high": 3,
            "bandit_medium": 5,
            "mypy_errors": 10,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert qp.maintainability.rating == "D"
        assert qp.complexity.rating == "D"
        assert qp.code_style.rating == "D"
        assert qp.documentation.rating == "D"
        assert qp.security.rating == "FAIL"
        assert qp.mypy_errors == 10

    def test_all_null_metrics(self):
        metrics = {
            "maintainability_index": None,
            "cognitive_complexity": None,
            "max_nesting_depth": None,
            "ruff_violations": None,
            "pylint_score": None,
            "docstring_density": None,
            "comment_density": None,
            "function_count": None,
            "loc": None,
            "bandit_high": None,
            "bandit_medium": None,
            "mypy_errors": None,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert qp.maintainability.rating is None
        assert qp.complexity.rating is None
        assert qp.code_style.rating is None
        assert qp.documentation.rating is None
        assert qp.security.rating is None
        assert qp.mypy_errors is None
        # Summary should not contain rated dimensions
        assert qp.summary == ""

    def test_mypy_env_sensitive(self):
        metrics = {
            "maintainability_index": 50.0,
            "cognitive_complexity": 3,
            "max_nesting_depth": 1,
            "ruff_violations": 0,
            "pylint_score": 9.5,
            "docstring_density": 0.90,
            "comment_density": 0.15,
            "function_count": 10,
            "loc": 100,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": 5,
            "data_warnings": ["suspect:mypy_env"],
        }
        qp = profile_file(metrics)
        assert qp.mypy_env_sensitive is True

    def test_summary_format(self):
        metrics = {
            "maintainability_index": 25.0,
            "cognitive_complexity": 18,
            "max_nesting_depth": 2,
            "ruff_violations": 0,
            "pylint_score": 9.2,
            "docstring_density": 0.10,
            "comment_density": 0.15,
            "function_count": 10,
            "loc": 100,
            "bandit_high": 0,
            "bandit_medium": 1,
            "mypy_errors": 2,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert qp.summary == "M:B Cx:C St:A Doc:D Sec:PASS"

    def test_summary_excludes_null_dimensions(self):
        """Dimensions with None rating should not appear in summary."""
        metrics = {
            "maintainability_index": 50.0,
            "cognitive_complexity": None,
            "max_nesting_depth": None,
            "ruff_violations": 0,
            "pylint_score": None,
            "docstring_density": None,
            "comment_density": None,
            "function_count": None,
            "loc": None,
            "bandit_high": 0,
            "bandit_medium": 0,
            "mypy_errors": None,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert qp.summary == "M:A St:A Sec:PASS"


# ===================================================================
# Output field mapping (qp_* fields for annotator integration)
# ===================================================================


class TestOutputFields:
    """Verify profile_file output can be converted to qp_* flat fields."""

    def test_to_flat_dict(self):
        metrics = {
            "maintainability_index": 52.3,
            "cognitive_complexity": 18,
            "max_nesting_depth": 2,
            "ruff_violations": 0,
            "pylint_score": 9.2,
            "docstring_density": 0.10,
            "comment_density": 0.15,
            "function_count": 10,
            "loc": 100,
            "bandit_high": 0,
            "bandit_medium": 1,
            "mypy_errors": 2,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        flat = qp.to_flat_dict()

        assert flat["qp_maintainability"] == "A"
        assert flat["qp_maintainability_limiting"] is None
        assert flat["qp_maintainability_detail"] == {"maintainability_index": "A"}

        assert flat["qp_complexity"] == "C"
        assert flat["qp_complexity_limiting"] == "cognitive_complexity"
        assert flat["qp_complexity_detail"] == {
            "cognitive_complexity": "C",
            "max_nesting_depth": "A",
        }

        assert flat["qp_code_style"] == "A"
        assert flat["qp_code_style_limiting"] is None
        assert flat["qp_code_style_detail"] == {
            "ruff_violations": "A",
            "pylint_score": "A",
        }

        assert flat["qp_documentation"] == "D"
        assert flat["qp_documentation_limiting"] == "docstring_density"

        assert flat["qp_security"] == "PASS"
        assert flat["qp_security_detail"] == {"bandit_high": 0, "bandit_medium": 1}

        assert flat["qp_mypy_errors"] == 2
        assert flat["qp_mypy_env_sensitive"] is False
        assert flat["qp_summary"] == "M:A Cx:C St:A Doc:D Sec:PASS"
