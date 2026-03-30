"""Tests for TypeScriptAnalyzer (analyzers/typescript.py).

Unit tests use mocked subprocess; integration tests require Node.js.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dr_huatuo.analyzers.typescript import TypeScriptAnalyzer

# ===================================================================
# Skip if Node.js not installed
# ===================================================================

has_node = shutil.which("node") is not None
requires_node = pytest.mark.skipif(not has_node, reason="Node.js not installed")


# ===================================================================
# Protocol conformance (no Node.js needed)
# ===================================================================


class TestProtocolConformance:
    def test_classvars(self):
        assert TypeScriptAnalyzer.name == "typescript"
        assert ".ts" in TypeScriptAnalyzer.extensions
        assert ".tsx" in TypeScriptAnalyzer.extensions
        assert "node" in TypeScriptAnalyzer.critical_tools
        assert "eslint" in TypeScriptAnalyzer.critical_tools

    def test_is_registered(self):
        from dr_huatuo.analyzers import ANALYZERS

        assert ANALYZERS.get(".ts") is TypeScriptAnalyzer
        assert ANALYZERS.get(".tsx") is TypeScriptAnalyzer


# ===================================================================
# Text-based metrics (no Node.js needed)
# ===================================================================


class TestTextMetrics:
    def test_count_functions(self):
        source = """
function foo() {}
const bar = () => {
    return 1;
}
async function baz() {}
"""
        assert TypeScriptAnalyzer._count_functions(source) >= 3

    def test_count_classes(self):
        source = """
class Foo {}
class Bar extends Foo {}
"""
        assert TypeScriptAnalyzer._count_classes(source) == 2

    def test_comment_density(self):
        source = "// comment\nconst x = 1;\nconst y = 2;\n"
        density = TypeScriptAnalyzer._comment_density(source, 3)
        assert density == pytest.approx(1 / 3, abs=0.01)

    def test_comment_density_block(self):
        source = "/* block\n   comment */\nconst x = 1;\n"
        density = TypeScriptAnalyzer._comment_density(source, 3)
        assert density == pytest.approx(2 / 3, abs=0.01)

    def test_jsdoc_density(self):
        source = "/** docs */\nfunction foo() {}\nfunction bar() {}\n"
        assert TypeScriptAnalyzer._jsdoc_density(source, 2) == pytest.approx(0.5)

    def test_nesting_depth(self):
        source = "function f() { if (x) { for (;;) { } } }"
        # function{1} -> if{2} -> for{3}, minus 1 wrapper = 2
        assert TypeScriptAnalyzer._nesting_depth(source) >= 2

    def test_empty_file(self):
        assert TypeScriptAnalyzer._count_functions("") == 0
        assert TypeScriptAnalyzer._count_classes("") == 0
        assert TypeScriptAnalyzer._comment_density("", 0) == 0.0
        assert TypeScriptAnalyzer._jsdoc_density("", 0) == 0.0


# ===================================================================
# Missing tool handling
# ===================================================================


class TestMissingTools:
    def test_missing_node_raises(self, monkeypatch):
        original_which = shutil.which

        def fake_which(name, **kwargs):
            if name == "node":
                return None
            return original_which(name, **kwargs)

        monkeypatch.setattr(shutil, "which", fake_which)

        from dr_huatuo.analyzers.base import ToolNotFoundError

        with pytest.raises(ToolNotFoundError, match="node"):
            TypeScriptAnalyzer()

    def test_missing_eslint_raises(self, monkeypatch):
        original_which = shutil.which

        def fake_which(name, **kwargs):
            if name == "eslint":
                return None
            return original_which(name, **kwargs)

        monkeypatch.setattr(shutil, "which", fake_which)

        from dr_huatuo.analyzers.base import ToolNotFoundError

        with pytest.raises(ToolNotFoundError, match="eslint"):
            TypeScriptAnalyzer()


# ===================================================================
# Mocked subprocess tests
# ===================================================================


class TestEslintParsing:
    def test_parse_eslint_json(self, monkeypatch):
        """Test eslint JSON output parsing with mocked subprocess."""
        eslint_output = json.dumps(
            [
                {
                    "filePath": "/tmp/test.ts",
                    "messages": [
                        {
                            "ruleId": "no-unused-vars",
                            "severity": 2,
                            "message": "unused",
                        },
                        {"ruleId": "no-console", "severity": 1, "message": "console"},
                        {
                            "ruleId": "security/detect-object-injection",
                            "severity": 2,
                            "message": "obj injection",
                        },
                    ],
                }
            ]
        )

        import subprocess

        original_run = subprocess.run

        def mock_run(cmd, **kwargs):
            if cmd[0] == "eslint":
                return subprocess.CompletedProcess(
                    cmd, returncode=1, stdout=eslint_output, stderr=""
                )
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)

        # Create analyzer instance without real tool checks
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {"node": "node", "eslint": "eslint"}

        from pathlib import Path

        result = analyzer._run_eslint([Path("/tmp/test.ts")])
        assert result is not None
        file_data = result["/tmp/test.ts"]
        assert file_data["lint_violations"] == 2  # no-unused-vars + no-console
        assert file_data["security_high"] == 1


# ===================================================================
# Integration tests (require Node.js + eslint)
# ===================================================================


@requires_node
class TestIntegration:
    def test_analyze_file_returns_all_keys(self, tmp_path):
        f = tmp_path / "test.ts"
        f.write_text("const x: number = 1;\nconsole.log(x);\n")

        try:
            analyzer = TypeScriptAnalyzer(project_root=tmp_path)
        except Exception:
            pytest.skip("eslint not installed")

        result = analyzer.analyze_file(f)

        # All protocol keys present
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
            assert key in result, f"Missing key: {key}"

        assert result["language"] == "typescript"
        assert result["loc"] == 2

    def test_analyze_batch_preserves_order(self, tmp_path):
        f1 = tmp_path / "a.ts"
        f2 = tmp_path / "b.ts"
        f1.write_text("const a = 1;\n")
        f2.write_text("const b = 2;\nconst c = 3;\n")

        try:
            analyzer = TypeScriptAnalyzer(project_root=tmp_path)
        except Exception:
            pytest.skip("eslint not installed")

        results = analyzer.analyze_batch([f1, f2])
        assert len(results) == 2
        assert results[0]["loc"] == 1
        assert results[1]["loc"] == 2


# ===================================================================
# CLI discovery tests (no Node.js needed)
# ===================================================================


class TestCliDiscovery:
    def test_discover_finds_ts_files(self, tmp_path):
        (tmp_path / "app.ts").write_text("const x = 1;\n")
        (tmp_path / "comp.tsx").write_text("const y = 2;\n")
        (tmp_path / "util.py").write_text("x = 1\n")

        from dr_huatuo.cli import _discover_files

        files = list(_discover_files(str(tmp_path), []))
        extensions = {f.suffix for f in files}
        assert ".ts" in extensions
        assert ".tsx" in extensions
        assert ".py" in extensions

    def test_language_filter_python(self, tmp_path):
        (tmp_path / "app.ts").write_text("const x = 1;\n")
        (tmp_path / "util.py").write_text("x = 1\n")

        from dr_huatuo.cli import _discover_files

        files = list(_discover_files(str(tmp_path), [], language="python"))
        assert all(f.suffix == ".py" for f in files)

    def test_language_filter_typescript(self, tmp_path):
        (tmp_path / "app.ts").write_text("const x = 1;\n")
        (tmp_path / "util.py").write_text("x = 1\n")

        from dr_huatuo.cli import _discover_files

        files = list(_discover_files(str(tmp_path), [], language="typescript"))
        assert all(f.suffix in (".ts", ".tsx") for f in files)


# ===================================================================
# Tsc output parsing
# ===================================================================


class TestTscParsing:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {"node": "node", "eslint": "eslint", "tsc": "tsc"}
        return analyzer

    def test_tsc_clean_returns_zero_per_file(self, monkeypatch):
        """tsc exit 0 with no output means zero type errors for all files."""
        paths = [Path("/tmp/a.ts"), Path("/tmp/b.ts")]

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_tsc(paths)
        assert result is not None
        assert result["/tmp/a.ts"] == 0
        assert result["/tmp/b.ts"] == 0

    def test_tsc_parses_error_lines(self, monkeypatch):
        """tsc exit 1 with error lines populates per-file counts."""
        paths = [Path("/tmp/a.ts")]
        tsc_output = "/tmp/a.ts(3,5): error TS2322: Type 'string' is not assignable.\n"

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout=tsc_output, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_tsc(paths)
        assert result is not None
        assert result["/tmp/a.ts"] >= 1

    def test_tsc_timeout_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 60)

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_tsc([Path("/tmp/a.ts")])
        assert result is None


# ===================================================================
# Escomplex output parsing
# ===================================================================


class TestEscomplexParsing:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {
            "node": "node",
            "eslint": "eslint",
            "escomplex": "escomplex",
        }
        return analyzer

    def test_escomplex_parses_metrics(self, monkeypatch):
        """Valid escomplex JSON is parsed into the expected keys."""
        payload = json.dumps(
            {"cyclomatic": 3, "avg_cyclomatic": 1.5, "maintainability": 85.2}
        )

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=payload, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_escomplex(Path("/tmp/test.ts"))
        assert result is not None
        assert result["cyclomatic"] == 3
        assert result["avg_cyclomatic"] == pytest.approx(1.5, abs=0.01)
        assert result["maintainability"] == pytest.approx(85.2, abs=0.1)

    def test_escomplex_passes_path_as_argv(self, monkeypatch):
        """Path must be passed as a CLI argument, not embedded in the script."""
        captured: list[list[str]] = []

        def mock_run(cmd, **kwargs):
            captured.append(list(cmd))
            payload = json.dumps(
                {"cyclomatic": 1, "avg_cyclomatic": 1.0, "maintainability": 100.0}
            )
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=payload, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        analyzer._run_escomplex(Path("/some/path/file.ts"))

        assert len(captured) == 1
        cmd = captured[0]
        # cmd must be: ["node", "-e", <script>, "/some/path/file.ts"]
        assert cmd[0] == "node"
        assert cmd[1] == "-e"
        assert cmd[3] == "/some/path/file.ts"
        # The path must NOT appear inside the inline script string
        assert "/some/path/file.ts" not in cmd[2]

    def test_escomplex_error_json_returns_none(self, monkeypatch):
        """Node script returning {error: ...} maps to None."""
        payload = json.dumps({"error": "unexpected token"})

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=payload, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_escomplex(Path("/tmp/test.ts"))
        assert result is None

    def test_escomplex_nonzero_exit_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="module not found"
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_escomplex(Path("/tmp/test.ts"))
        assert result is None


# ===================================================================
# Batch failure propagation
# ===================================================================


class TestBatchFailures:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {
            "node": "node",
            "eslint": "eslint",
            "tsc": "tsc",
            "escomplex": None,
        }
        return analyzer

    def test_eslint_none_sets_tool_error(self, tmp_path, monkeypatch):
        """When _run_eslint returns None, each result has eslint in tool_errors."""
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: None)
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: {str(f): 0})
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        results = analyzer.analyze_batch([f])
        assert len(results) == 1
        r = results[0]
        assert r["tool_errors"] is not None
        assert "eslint" in r["tool_errors"]
        assert "eslint_failed" in " ".join(r["data_warnings"])

    def test_tsc_none_sets_tool_error(self, tmp_path, monkeypatch):
        """When _run_tsc returns None, each result has tsc in tool_errors."""
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()
        clean_eslint = {
            str(f): {
                "lint_violations": 0,
                "security_high": 0,
                "security_medium": 0,
                "cognitive_complexity": None,
            }
        }
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: clean_eslint)
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: None)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        results = analyzer.analyze_batch([f])
        assert len(results) == 1
        r = results[0]
        assert r["tool_errors"] is not None
        assert "tsc" in r["tool_errors"]
        assert "tsc_failed" in " ".join(r["data_warnings"])


# ===================================================================
# Security PASS: clean file gets 0 not None
# ===================================================================


class TestSecurityPass:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {"node": "node", "eslint": "eslint"}
        return analyzer

    def test_clean_file_security_high_is_zero(self, monkeypatch):
        """When eslint finds no security violations, security_high must be 0."""
        eslint_output = json.dumps([{"filePath": "/tmp/clean.ts", "messages": []}])

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=eslint_output, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_eslint([Path("/tmp/clean.ts")])
        assert result is not None
        file_data = result["/tmp/clean.ts"]
        assert file_data["security_high"] == 0
        assert file_data["security_medium"] == 0

    def test_clean_file_no_security_plugin_returns_zero(self, monkeypatch):
        """Lint violations only (no security rules) — security_high must be 0."""
        eslint_output = json.dumps(
            [
                {
                    "filePath": "/tmp/lint_only.ts",
                    "messages": [
                        {"ruleId": "no-console", "severity": 1, "message": "console"},
                    ],
                }
            ]
        )

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout=eslint_output, stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_eslint([Path("/tmp/lint_only.ts")])
        assert result is not None
        file_data = result["/tmp/lint_only.ts"]
        assert file_data["security_high"] == 0
        assert file_data["security_medium"] == 0

    def test_empty_stdout_crash_returns_none(self, monkeypatch):
        """Empty stdout with non-0/1 exit code must return None, not {}."""

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=2, stdout="", stderr="Fatal error"
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_eslint([Path("/tmp/test.ts")])
        assert result is None

    def test_empty_stdout_returncode_0_returns_empty_dict(self, monkeypatch):
        """Empty stdout with exit 0 means no files matched — return {}."""

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        result = analyzer._run_eslint([Path("/tmp/test.ts")])
        assert result == {}
