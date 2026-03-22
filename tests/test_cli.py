"""Tests for cli.py — unified CLI entry point.

Tests cover:
- Subcommand routing (check, report, version)
- File discovery (single file, directory, exclusion)
- Layer 2 metrics gathering (_gather_layer2)
- Quality gate logic (--fail-on with grade and dimension filtering)
- Terminal output rendering
- Security + grade interaction in quality gates
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ===================================================================
# Helper: run cli.py as subprocess for integration tests
# ===================================================================


def _run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run cli.py as a subprocess and return the result."""
    cmd = [sys.executable, "cli.py", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(Path(__file__).parent.parent),
        timeout=120,
    )


# ===================================================================
# File discovery
# ===================================================================


class TestDiscoverFiles:
    """Test _discover_files helper."""

    def test_single_py_file(self, tmp_path):
        from cli import _discover_files

        f = tmp_path / "hello.py"
        f.write_text("x = 1\n")
        result = list(_discover_files(str(f), []))
        assert result == [f]

    def test_directory_finds_py_files(self, tmp_path):
        from cli import _discover_files

        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        (tmp_path / "c.txt").write_text("not python\n")
        result = sorted(_discover_files(str(tmp_path), []))
        assert len(result) == 2
        assert all(f.suffix == ".py" for f in result)

    def test_directory_excludes_dirs(self, tmp_path):
        from cli import _discover_files

        sub = tmp_path / ".venv"
        sub.mkdir()
        (sub / "ignored.py").write_text("x = 1\n")
        (tmp_path / "keep.py").write_text("y = 2\n")
        result = list(_discover_files(str(tmp_path), [".venv"]))
        assert len(result) == 1
        assert result[0].name == "keep.py"

    def test_nonexistent_path_raises(self):
        from cli import _discover_files

        with pytest.raises(FileNotFoundError):
            list(_discover_files("/nonexistent/path.py", []))

    def test_nested_directory(self, tmp_path):
        from cli import _discover_files

        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("x = 1\n")
        (tmp_path / "top.py").write_text("y = 2\n")
        result = sorted(_discover_files(str(tmp_path), []))
        assert len(result) == 2


# ===================================================================
# Layer 2 metrics gathering
# ===================================================================


class TestGatherLayer2:
    """Test _gather_layer2 for computing missing fields."""

    def test_loc_counts_lines(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text("a = 1\nb = 2\nc = 3\n")
        result = _gather_layer2(str(f))
        assert result["loc"] == 3

    def test_function_count(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent("""\
            def foo():
                pass

            def bar():
                pass

            async def baz():
                pass
            """)
        )
        result = _gather_layer2(str(f))
        assert result["function_count"] == 3

    def test_class_count(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent("""\
            class Foo:
                pass

            class Bar:
                class Inner:
                    pass
            """)
        )
        result = _gather_layer2(str(f))
        assert result["class_count"] == 3

    def test_max_nesting_depth(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent("""\
            def foo():
                if True:
                    for x in []:
                        if x:
                            pass
            """)
        )
        result = _gather_layer2(str(f))
        assert result["max_nesting_depth"] == 3

    def test_docstring_density(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent('''\
            def foo():
                """Has a docstring."""
                pass

            def bar():
                pass
            ''')
        )
        result = _gather_layer2(str(f))
        assert result["docstring_density"] == pytest.approx(0.5)

    def test_comment_density(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text("# comment\nx = 1\ny = 2\n# another\nz = 3\n")
        result = _gather_layer2(str(f))
        assert result["comment_density"] == pytest.approx(2 / 5)

    def test_maintainability_index_present(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = _gather_layer2(str(f))
        # MI should be a float or None, not missing
        assert "maintainability_index" in result
        # For a trivial file, MI should be a positive number
        if result["maintainability_index"] is not None:
            assert result["maintainability_index"] > 0

    def test_data_warnings_default_empty(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = _gather_layer2(str(f))
        assert result["data_warnings"] == []

    def test_empty_file(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text("")
        result = _gather_layer2(str(f))
        assert result["loc"] == 0
        assert result["function_count"] == 0
        assert result["class_count"] == 0

    def test_cognitive_complexity_present(self, tmp_path):
        from cli import _gather_layer2

        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent("""\
            def foo():
                if True:
                    pass
            """)
        )
        result = _gather_layer2(str(f))
        # cognitive_complexity should be present (int or None if complexipy unavailable)
        assert "cognitive_complexity" in result


# ===================================================================
# Quality gate logic
# ===================================================================


class TestQualityGate:
    """Test _check_quality_gate logic."""

    def _make_profile(self, ratings: dict):
        """Create a mock QualityProfile with given dimension ratings.

        ratings: dict of dimension_name -> rating string (A/B/C/D or PASS/WARN/FAIL)
        """
        from quality_profile import DimensionResult, QualityProfile

        dims = {}
        for name in [
            "maintainability",
            "complexity",
            "code_style",
            "documentation",
        ]:
            rating = ratings.get(name, "A")
            dims[name] = DimensionResult(
                name=name, rating=rating, limiting_metric=None, detail={}
            )
        sec_rating = ratings.get("security", "PASS")
        dims["security"] = DimensionResult(
            name="security", rating=sec_rating, limiting_metric=None, detail={}
        )
        return QualityProfile(
            **dims,
            mypy_errors=0,
            mypy_env_sensitive=False,
            summary="",
        )

    def test_no_fail_on_returns_false(self):
        from cli import _check_quality_gate

        profile = self._make_profile({})
        assert _check_quality_gate([("test.py", profile)], None, None) is False

    def test_fail_on_d_all_a_passes(self):
        from cli import _check_quality_gate

        profile = self._make_profile({})
        assert _check_quality_gate([("test.py", profile)], "D", None) is False

    def test_fail_on_d_with_d_fails(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"complexity": "D"})
        assert _check_quality_gate([("test.py", profile)], "D", None) is True

    def test_fail_on_c_with_c_fails(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"documentation": "C"})
        assert _check_quality_gate([("test.py", profile)], "C", None) is True

    def test_fail_on_c_with_d_fails(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"documentation": "D"})
        assert _check_quality_gate([("test.py", profile)], "C", None) is True

    def test_fail_on_b_with_b_fails(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"maintainability": "B"})
        assert _check_quality_gate([("test.py", profile)], "B", None) is True

    def test_fail_on_b_all_a_passes(self):
        from cli import _check_quality_gate

        profile = self._make_profile({})
        assert _check_quality_gate([("test.py", profile)], "B", None) is False

    def test_fail_on_d_security_fail_triggers(self):
        """--fail-on D implicitly includes Security FAIL."""
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "FAIL"})
        assert _check_quality_gate([("test.py", profile)], "D", None) is True

    def test_fail_on_c_security_warn_triggers(self):
        """--fail-on C includes Security WARN."""
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "WARN"})
        assert _check_quality_gate([("test.py", profile)], "C", None) is True

    def test_fail_on_c_security_fail_triggers(self):
        """--fail-on C includes Security FAIL."""
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "FAIL"})
        assert _check_quality_gate([("test.py", profile)], "C", None) is True

    def test_fail_on_d_security_warn_does_not_trigger(self):
        """--fail-on D does NOT trigger on WARN (only FAIL)."""
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "WARN"})
        assert _check_quality_gate([("test.py", profile)], "D", None) is False

    def test_fail_on_fail_security_fail(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "FAIL"})
        assert _check_quality_gate([("test.py", profile)], "FAIL", None) is True

    def test_fail_on_fail_security_pass(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "PASS"})
        assert _check_quality_gate([("test.py", profile)], "FAIL", None) is False

    def test_fail_on_warn_security_warn(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "WARN"})
        assert _check_quality_gate([("test.py", profile)], "WARN", None) is True

    def test_fail_on_warn_security_fail(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"security": "FAIL"})
        assert _check_quality_gate([("test.py", profile)], "WARN", None) is True

    def test_dimension_filter_narrows_check(self):
        """--dimension security only checks security dimension."""
        from cli import _check_quality_gate

        profile = self._make_profile({"complexity": "D", "security": "PASS"})
        assert (
            _check_quality_gate([("test.py", profile)], "D", "security") is False
        )

    def test_dimension_filter_matching(self):
        from cli import _check_quality_gate

        profile = self._make_profile({"complexity": "D"})
        assert (
            _check_quality_gate([("test.py", profile)], "D", "complexity") is True
        )

    def test_multiple_files(self):
        from cli import _check_quality_gate

        p1 = self._make_profile({})
        p2 = self._make_profile({"complexity": "D"})
        assert (
            _check_quality_gate(
                [("good.py", p1), ("bad.py", p2)], "D", None
            )
            is True
        )

    def test_none_rating_does_not_trigger(self):
        """N/A dimensions should not trigger quality gate."""
        from cli import _check_quality_gate
        from quality_profile import DimensionResult, QualityProfile

        profile = QualityProfile(
            maintainability=DimensionResult(
                name="maintainability", rating=None, limiting_metric=None, detail={}
            ),
            complexity=DimensionResult(
                name="complexity", rating=None, limiting_metric=None, detail={}
            ),
            code_style=DimensionResult(
                name="code_style", rating=None, limiting_metric=None, detail={}
            ),
            documentation=DimensionResult(
                name="documentation", rating=None, limiting_metric=None, detail={}
            ),
            security=DimensionResult(
                name="security", rating=None, limiting_metric=None, detail={}
            ),
            mypy_errors=None,
            mypy_env_sensitive=False,
            summary="",
        )
        assert _check_quality_gate([("test.py", profile)], "D", None) is False


# ===================================================================
# Build metrics dict
# ===================================================================


class TestBuildMetricsDict:
    """Test _build_metrics_dict combining CodeMetrics + Layer 2."""

    def test_field_mapping(self):
        from cli import _build_metrics_dict
        from code_analyzer import CodeMetrics

        cm = CodeMetrics(
            file_path="test.py",
            max_cyclomatic_complexity=12,
            functions_analyzed=5,
            ruff_violations=3,
            pylint_score=8.5,
            mypy_errors=2,
            bandit_high=1,
            bandit_medium=0,
        )
        layer2 = {
            "maintainability_index": 45.0,
            "cognitive_complexity": 18,
            "max_nesting_depth": 3,
            "docstring_density": 0.60,
            "comment_density": 0.12,
            "loc": 100,
            "function_count": 5,
            "class_count": 2,
            "data_warnings": [],
        }
        result = _build_metrics_dict(cm, layer2)

        # CodeMetrics fields (mapped names)
        assert result["cyclomatic_complexity"] == 12
        assert result["function_count"] == 5  # from layer2, not functions_analyzed
        assert result["ruff_violations"] == 3
        assert result["pylint_score"] == 8.5
        assert result["mypy_errors"] == 2
        assert result["bandit_high"] == 1
        assert result["bandit_medium"] == 0

        # Layer 2 fields
        assert result["maintainability_index"] == 45.0
        assert result["cognitive_complexity"] == 18
        assert result["max_nesting_depth"] == 3
        assert result["docstring_density"] == 0.60
        assert result["comment_density"] == 0.12
        assert result["loc"] == 100
        assert result["class_count"] == 2
        assert result["data_warnings"] == []


# ===================================================================
# Subcommand: version
# ===================================================================


class TestVersionSubcommand:
    """Test the version subcommand."""

    def test_version_runs(self):
        result = _run_cli("version")
        assert result.returncode == 0
        assert "huatuo" in result.stdout.lower()

    def test_version_shows_tool_versions(self):
        result = _run_cli("version")
        assert result.returncode == 0
        # Should mention at least some tools
        output = result.stdout.lower()
        assert "ruff" in output or "radon" in output


# ===================================================================
# Subcommand: check (integration, uses real tools)
# ===================================================================


class TestCheckSubcommand:
    """Integration tests for `check` subcommand."""

    def test_check_single_file(self, tmp_path):
        f = tmp_path / "simple.py"
        f.write_text("x = 1\n")
        result = _run_cli("check", str(f))
        assert result.returncode == 0

    def test_check_nonexistent_file(self):
        result = _run_cli("check", "/nonexistent/path.py")
        assert result.returncode != 0

    def test_check_with_fail_on_accepted(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        result = _run_cli("check", str(f), "--fail-on", "D")
        # Should exit 0 (pass) or 1 (gate violation) — both are valid.
        # Exact result depends on whether pylint/bandit/mypy are on PATH.
        assert result.returncode in (0, 1)

    def test_check_no_args_shows_help(self):
        result = _run_cli("check")
        # argparse should show error or usage
        assert result.returncode != 0


# ===================================================================
# Subcommand: report (integration, delegates to code_reporter)
# ===================================================================


class TestReportSubcommand:
    """Integration tests for `report` subcommand."""

    def test_report_no_args_shows_help(self):
        result = _run_cli("report")
        assert result.returncode != 0

    def test_report_delegates_to_reporter(self, tmp_path):
        f = tmp_path / "simple.py"
        f.write_text("x = 1\n")
        result = _run_cli("report", str(f), "-f", "json")
        assert result.returncode == 0
        # Should produce JSON output
        assert "{" in result.stdout


# ===================================================================
# No subcommand
# ===================================================================


class TestNoSubcommand:
    """Test behavior when no subcommand is given."""

    def test_no_args_shows_usage(self):
        result = _run_cli()
        # Should show help/usage
        assert result.returncode != 0 or "usage" in result.stdout.lower()
