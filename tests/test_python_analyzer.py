"""Tests for PythonAnalyzer (analyzers/python.py).

Migrated from test_cli.py TestGatherLayer2 and TestBuildMetricsDict.
Tests Layer 2 metrics (AST, radon, complexipy) and the full analyze_file output.
"""

import textwrap

import pytest

from dr_huatuo.analyzers.python import PythonAnalyzer


@pytest.fixture
def analyzer():
    """Create a PythonAnalyzer instance."""
    return PythonAnalyzer()


# ===================================================================
# Layer 2 metrics (migrated from TestGatherLayer2)
# ===================================================================


class TestLayer2Metrics:
    """Test PythonAnalyzer._gather_layer2 for computing AST metrics."""

    def test_loc_counts_lines(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("a = 1\nb = 2\nc = 3\n")
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["loc"] == 3

    def test_function_count(self, tmp_path):
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
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["function_count"] == 3

    def test_class_count(self, tmp_path):
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
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["class_count"] == 3

    def test_max_nesting_depth(self, tmp_path):
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
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["max_nesting_depth"] == 3

    def test_docstring_density(self, tmp_path):
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
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["docstring_density"] == pytest.approx(0.5)

    def test_comment_density(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("# comment\nx = 1\ny = 2\n# another\nz = 3\n")
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["comment_density"] == pytest.approx(2 / 5)

    def test_maintainability_index_present(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = PythonAnalyzer._gather_layer2(str(f))
        assert "maintainability_index" in result
        if result["maintainability_index"] is not None:
            assert result["maintainability_index"] > 0

    def test_data_warnings_default_empty(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["data_warnings"] == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("")
        result = PythonAnalyzer._gather_layer2(str(f))
        assert result["loc"] == 0
        assert result["function_count"] == 0
        assert result["class_count"] == 0

    def test_cognitive_complexity_present(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text(
            textwrap.dedent("""\
            def foo():
                if True:
                    pass
            """)
        )
        result = PythonAnalyzer._gather_layer2(str(f))
        assert "cognitive_complexity" in result


# ===================================================================
# Full analyze_file output (migrated from TestBuildMetricsDict)
# ===================================================================


class TestAnalyzeFile:
    """Test PythonAnalyzer.analyze_file returns the full protocol dict."""

    def test_output_has_all_protocol_keys(self, analyzer, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = analyzer.analyze_file(f)

        # Protocol-required keys
        for key in [
            "cyclomatic_complexity",
            "avg_complexity",
            "cognitive_complexity",
            "max_nesting_depth",
            "loc",
            "function_count",
            "class_count",
            "maintainability_index",
            "comment_density",
            "docstring_density",
            "lint_violations",
            "linter_score",
            "security_high",
            "security_medium",
            "type_errors",
            "language",
            "data_warnings",
            "error_type",
            "error_detail",
            "tool_errors",
        ]:
            assert key in result, f"Missing protocol key: {key}"

        # Halstead keys
        for key in [
            "n1", "n2", "N1", "N2",
            "halstead_volume", "halstead_difficulty", "halstead_effort",
        ]:
            assert key in result, f"Missing Halstead key: {key}"

        # Legacy backward-compat keys
        for key in [
            "ruff_violations",
            "pylint_score",
            "bandit_high",
            "bandit_medium",
            "mypy_errors",
        ]:
            assert key in result, f"Missing legacy key: {key}"

    def test_language_is_python(self, analyzer, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = analyzer.analyze_file(f)
        assert result["language"] == "python"

    def test_dual_emit_consistency(self, analyzer, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        result = analyzer.analyze_file(f)
        assert result["lint_violations"] == result["ruff_violations"]
        assert result["security_high"] == result["bandit_high"]
        assert result["security_medium"] == result["bandit_medium"]
        assert result["type_errors"] == result["mypy_errors"]
        assert result["linter_score"] == result["pylint_score"]


# ===================================================================
# Protocol conformance
# ===================================================================


class TestMissingTools:
    """Test error handling when tools are missing."""

    def test_missing_critical_tool_raises(self, monkeypatch):
        import shutil

        original_which = shutil.which

        def fake_which(name, **kwargs):
            if name == "ruff":
                return None
            return original_which(name, **kwargs)

        monkeypatch.setattr(shutil, "which", fake_which)

        from dr_huatuo.analyzers.base import ToolNotFoundError

        with pytest.raises(ToolNotFoundError, match="ruff"):
            PythonAnalyzer()

    def test_missing_optional_tool_warns(self, monkeypatch, capsys):
        import shutil

        original_which = shutil.which

        def fake_which(name, **kwargs):
            if name == "complexipy":
                return None
            return original_which(name, **kwargs)

        monkeypatch.setattr(shutil, "which", fake_which)
        analyzer = PythonAnalyzer()
        assert analyzer._tool_versions["complexipy"] is None
        captured = capsys.readouterr()
        assert "complexipy" in captured.out

    def test_all_critical_tools_missing_raises(self, monkeypatch):
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name, **kw: None)

        from dr_huatuo.analyzers.base import ToolNotFoundError

        with pytest.raises(ToolNotFoundError):
            PythonAnalyzer()


class TestProtocolConformance:
    """Test PythonAnalyzer satisfies LanguageAnalyzer protocol."""

    def test_classvars(self):
        assert PythonAnalyzer.name == "python"
        assert PythonAnalyzer.extensions == [".py"]
        assert "ruff" in PythonAnalyzer.critical_tools
        assert "complexipy" in PythonAnalyzer.optional_tools

    def test_is_registered(self):
        from dr_huatuo.analyzers import ANALYZERS

        assert ANALYZERS.get(".py") is PythonAnalyzer

    def test_analyze_batch_delegates(self, analyzer, tmp_path):
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("x = 1\n")
        f2.write_text("y = 2\n")
        results = analyzer.analyze_batch([f1, f2])
        assert len(results) == 2
        assert results[0]["language"] == "python"
        assert results[1]["language"] == "python"
