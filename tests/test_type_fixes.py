"""Tests for CHG-2105: Fix Type Errors.

Verify that CodeMetrics default_factory works correctly and that
Path inputs are accepted at all entry points.
"""

from unittest.mock import patch

from code_analyzer import CodeMetrics


class TestCodeMetricsDefaults:
    """Verify field(default_factory=list) replaced __post_init__."""

    def test_ruff_errors_defaults_to_empty_list(self):
        m = CodeMetrics(file_path="x")
        assert m.ruff_errors == []

    def test_mypy_warnings_defaults_to_empty_list(self):
        m = CodeMetrics(file_path="x")
        assert m.mypy_warnings == []

    def test_bandit_issues_defaults_to_empty_list(self):
        m = CodeMetrics(file_path="x")
        assert m.bandit_issues == []

    def test_distinct_list_objects(self):
        """Two instances must not share the same list objects."""
        a = CodeMetrics(file_path="a")
        b = CodeMetrics(file_path="b")
        assert a.ruff_errors is not b.ruff_errors
        assert a.mypy_warnings is not b.mypy_warnings
        assert a.bandit_issues is not b.bandit_issues


class TestAnalyzeAcceptsPath:
    """Verify analyze() accepts Path input without error."""

    def test_analyze_with_path_input(self, tmp_path):
        """CodeAnalyzer.analyze() should accept a Path object."""
        dummy = tmp_path / "dummy.py"
        dummy.write_text("x = 1\n")

        from code_analyzer import CodeAnalyzer

        # Monkeypatch all external tool calls to avoid tool dependency
        with (
            patch.object(CodeAnalyzer, "_check_tools"),
            patch.object(CodeAnalyzer, "_run_ruff", return_value=[]),
            patch.object(
                CodeAnalyzer,
                "_run_radon",
                return_value={"max": 0, "avg": 0, "count": 0},
            ),
            patch.object(CodeAnalyzer, "_run_bandit", return_value=[]),
            patch.object(CodeAnalyzer, "_run_mypy", return_value=[]),
            patch.object(CodeAnalyzer, "_run_pylint", return_value=0.0),
        ):
            analyzer = CodeAnalyzer()
            metrics = analyzer.analyze(dummy)  # Path, not str

        assert metrics.file_path == str(dummy)
