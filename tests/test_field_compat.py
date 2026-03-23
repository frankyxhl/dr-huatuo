"""Tests for backward-compatible field name aliases.

Verifies that old field names (ruff_violations, bandit_high, etc.) still work
in both __init__ kwargs and attribute access, emitting DeprecationWarning.
"""

import warnings

from dr_huatuo.code_analyzer import CodeMetrics
from dr_huatuo.code_reporter import FileMetrics
from dr_huatuo.quality_profile import profile_file


class TestCodeMetricsCompat:
    """Old field names work on CodeMetrics."""

    def test_old_kwargs_in_init(self):
        m = CodeMetrics(
            file_path="t.py",
            ruff_violations=3,
            pylint_score=8.5,
            mypy_errors=2,
            bandit_high=1,
            bandit_medium=0,
        )
        assert m.lint_violations == 3
        assert m.linter_score == 8.5
        assert m.type_errors == 2
        assert m.security_high == 1
        assert m.security_medium == 0

    def test_old_attr_access_returns_value(self):
        m = CodeMetrics(file_path="t.py", lint_violations=5)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert m.ruff_violations == 5
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "ruff_violations" in str(w[0].message)

    def test_new_names_no_warning(self):
        m = CodeMetrics(file_path="t.py", lint_violations=5)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = m.lint_violations
            assert len(w) == 0


class TestFileMetricsCompat:
    """Old field names work on FileMetrics."""

    def test_old_kwargs_in_init(self):
        m = FileMetrics(
            file_path="t.py",
            ruff_violations=3,
            mypy_errors=2,
            bandit_high=1,
            bandit_medium=0,
        )
        assert m.lint_violations == 3
        assert m.type_errors == 2
        assert m.security_high == 1
        assert m.security_medium == 0

    def test_old_attr_access_warns(self):
        m = FileMetrics(file_path="t.py", lint_violations=7)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert m.ruff_violations == 7
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)


class TestQualityProfileCompat:
    """Old field names work on QualityProfile."""

    def test_old_mypy_errors_attr(self):
        metrics = {
            "maintainability_index": 50.0,
            "cognitive_complexity": 5,
            "max_nesting_depth": 1,
            "lint_violations": 0,
            "linter_score": 9.0,
            "docstring_density": 0.5,
            "comment_density": 0.1,
            "function_count": 5,
            "loc": 50,
            "security_high": 0,
            "security_medium": 0,
            "type_errors": 3,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert qp.mypy_errors == 3
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)


class TestProfileFileOldKeys:
    """profile_file() accepts dicts with old key names."""

    def test_old_key_names(self):
        metrics = {
            "maintainability_index": 50.0,
            "cognitive_complexity": 5,
            "max_nesting_depth": 1,
            "ruff_violations": 2,
            "pylint_score": 9.0,
            "docstring_density": 0.5,
            "comment_density": 0.1,
            "function_count": 5,
            "loc": 50,
            "bandit_high": 0,
            "bandit_medium": 1,
            "mypy_errors": 3,
            "data_warnings": [],
        }
        qp = profile_file(metrics)
        assert qp.type_errors == 3
        assert qp.security is not None
