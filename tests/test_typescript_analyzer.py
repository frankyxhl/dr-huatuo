"""Tests for TypeScriptAnalyzer (analyzers/typescript.py).

Unit tests use mocked subprocess; integration tests require Node.js.
"""

import json
import os
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


# ===================================================================
# _find_config_root walk-up logic
# ===================================================================


class TestFindConfigRoot:
    def test_none_returns_none(self):
        assert TypeScriptAnalyzer._find_config_root(None) is None

    def test_file_input_uses_parent(self, tmp_path):
        """When start is a file, config search begins from its parent."""
        (tmp_path / "tsconfig.json").write_text("{}")
        f = tmp_path / "app.ts"
        f.write_text("const x = 1;\n")
        result = TypeScriptAnalyzer._find_config_root(f)
        assert result == tmp_path.resolve()

    def test_finds_tsconfig(self, tmp_path):
        """Finds tsconfig.json in walk-up."""
        (tmp_path / "tsconfig.json").write_text("{}")
        sub = tmp_path / "src"
        sub.mkdir()
        result = TypeScriptAnalyzer._find_config_root(sub)
        assert result == tmp_path.resolve()

    def test_finds_eslint_config(self, tmp_path):
        """Finds .eslintrc.json in walk-up."""
        (tmp_path / ".eslintrc.json").write_text("{}")
        sub = tmp_path / "src"
        sub.mkdir()
        result = TypeScriptAnalyzer._find_config_root(sub)
        assert result == tmp_path.resolve()

    def test_stops_at_git_root(self, tmp_path):
        """Stops at .git directory even without config files."""
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "src"
        sub.mkdir()
        result = TypeScriptAnalyzer._find_config_root(sub)
        assert result == tmp_path.resolve()

    def test_fallback_to_original(self, tmp_path):
        """Returns original dir when nothing found (no config, no .git)."""
        sub = tmp_path / "isolated"
        sub.mkdir()
        result = TypeScriptAnalyzer._find_config_root(sub)
        # Falls back when walk-up finds nothing
        assert result is not None


# ===================================================================
# _ensure_node_on_path caching
# ===================================================================


class TestEnsureNodeOnPath:
    def test_runs_once_then_cached(self, monkeypatch):
        """_ensure_node_on_path runs npm bin only once, then caches."""
        call_count = [0]
        original_run = subprocess.run

        def counting_run(cmd, **kwargs):
            if cmd[:3] == ["npm", "bin", "-g"]:
                call_count[0] += 1
            return original_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", counting_run)
        # Reset cache
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)

        TypeScriptAnalyzer._ensure_node_on_path()
        TypeScriptAnalyzer._ensure_node_on_path()
        assert call_count[0] == 1  # only called once

        # Restore
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)

    def test_npm_bin_exception_handled(self, monkeypatch):
        """_ensure_node_on_path handles npm bin failure gracefully."""
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)

        def failing_run(cmd, **kwargs):
            if cmd[:3] == ["npm", "bin", "-g"]:
                raise OSError("npm not found")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", failing_run)
        # Should not raise
        TypeScriptAnalyzer._ensure_node_on_path()
        assert TypeScriptAnalyzer._path_ensured is True
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)

    def test_npm_bin_success_adds_to_path(self, monkeypatch):
        """npm bin -g result is added to PATH."""
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)
        fake_dir = "/fake/npm/global/bin"

        def mock_run(cmd, **kwargs):
            if cmd[:3] == ["npm", "bin", "-g"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=fake_dir + "\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        old_path = os.environ.get("PATH", "")
        TypeScriptAnalyzer._ensure_node_on_path()
        new_path = os.environ.get("PATH", "")
        assert fake_dir in new_path
        # Restore
        os.environ["PATH"] = old_path
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)


# ===================================================================
# _check_npm_package edge cases
# ===================================================================


class TestAddLocalNodeBins:
    def test_adds_project_root_node_modules(self, tmp_path, monkeypatch):
        """Adds project_root/node_modules/.bin to PATH if it exists."""
        bin_dir = tmp_path / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = tmp_path

        old_path = os.environ.get("PATH", "")
        analyzer._add_local_node_bins()
        new_path = os.environ.get("PATH", "")
        assert str(bin_dir) in new_path
        os.environ["PATH"] = old_path

    def test_skips_nonexistent_dir(self, tmp_path):
        """Does not add to PATH if node_modules/.bin doesn't exist."""
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = tmp_path

        old_path = os.environ.get("PATH", "")
        analyzer._add_local_node_bins()
        new_path = os.environ.get("PATH", "")
        node_bin = str(tmp_path / "node_modules" / ".bin")
        assert node_bin not in new_path
        os.environ["PATH"] = old_path


class TestTscListFiles:
    def _make_analyzer(self, project_root) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = project_root
        analyzer._tool_versions = {"tsc": "tsc"}
        return analyzer

    def test_returns_resolved_paths(self, tmp_path, monkeypatch):
        (tmp_path / "tsconfig.json").write_text("{}")

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0, stdout="/abs/path/a.ts\n/abs/path/b.ts\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(tmp_path)
        result = analyzer._tsc_list_files()
        assert "/abs/path/a.ts" in result
        assert "/abs/path/b.ts" in result

    def test_exception_returns_empty_set(self, tmp_path, monkeypatch):
        (tmp_path / "tsconfig.json").write_text("{}")

        def mock_run(cmd, **kwargs):
            raise OSError("tsc not found")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(tmp_path)
        assert analyzer._tsc_list_files() == set()

    def test_filters_error_lines(self, tmp_path, monkeypatch):
        (tmp_path / "tsconfig.json").write_text("{}")

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 1, stdout="/a.ts\nerror TS6053: ...\n/b.ts\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(tmp_path)
        result = analyzer._tsc_list_files()
        assert "/a.ts" in result
        assert "/b.ts" in result
        assert not any("error" in s for s in result)


class TestCheckNpmPackage:
    def test_invalid_package_name_rejected(self):
        """Package names with injection chars are rejected."""
        assert TypeScriptAnalyzer._check_npm_package("'); process.exit(1); //") is False

    def test_valid_scoped_package_accepted(self, monkeypatch):
        """Valid scoped npm package name passes regex."""

        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert TypeScriptAnalyzer._check_npm_package("@types/node") is True

    def test_subprocess_exception_returns_false(self, monkeypatch):
        """Exception during require() returns False."""

        def mock_run(cmd, **kwargs):
            raise OSError("node not found")

        monkeypatch.setattr(subprocess, "run", mock_run)
        assert TypeScriptAnalyzer._check_npm_package("some-package") is False


# ===================================================================
# analyze_file (mocked, full coverage)
# ===================================================================


class TestAnalyzeFileMocked:
    def _make_analyzer(self, **tool_versions) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {
            "node": "node",
            "eslint": "eslint",
            "tsc": "tsc",
            "escomplex": "escomplex",
            **tool_versions,
        }
        return analyzer

    def test_all_tools_succeed(self, tmp_path, monkeypatch):
        """analyze_file with all tools returning valid data."""
        f = tmp_path / "test.ts"
        f.write_text("function foo() { return 1; }\n")
        analyzer = self._make_analyzer()

        eslint_result = {
            str(f): {
                "lint_violations": 2,
                "security_high": 1,
                "security_medium": 0,
                "cognitive_complexity": 5,
            }
        }
        tsc_result = {str(f): 3}
        esc_result = {"cyclomatic": 4, "avg_cyclomatic": 2.0, "maintainability": 80.0}

        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: eslint_result)
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: tsc_result)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: esc_result)

        result = analyzer.analyze_file(f)
        assert result["lint_violations"] == 2
        assert result["security_high"] == 1
        assert result["type_errors"] == 3
        assert result["cyclomatic_complexity"] == 4
        assert result["maintainability_index"] == 80.0
        assert result["language"] == "typescript"
        assert result["loc"] == 1
        assert result["error_type"] is None

    def test_eslint_fails(self, tmp_path, monkeypatch):
        """analyze_file when eslint returns None."""
        f = tmp_path / "test.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()

        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: None)
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: {str(f): 0})
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        result = analyzer.analyze_file(f)
        assert "eslint" in result["tool_errors"]
        assert "eslint_failed" in " ".join(result["data_warnings"])

    def test_tsc_not_available(self, tmp_path, monkeypatch):
        """analyze_file when tsc is not installed."""
        f = tmp_path / "test.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer(tsc=None)

        monkeypatch.setattr(
            analyzer, "_run_eslint", lambda paths: {str(f): {"lint_violations": 0}}
        )
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        result = analyzer.analyze_file(f)
        assert result["type_errors"] is None
        assert "no_tsc" in " ".join(result["data_warnings"])

    def test_tsc_fails(self, tmp_path, monkeypatch):
        """analyze_file when tsc returns None (crash)."""
        f = tmp_path / "test.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()

        monkeypatch.setattr(
            analyzer, "_run_eslint", lambda paths: {str(f): {"lint_violations": 0}}
        )
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: None)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        result = analyzer.analyze_file(f)
        assert "tsc" in result["tool_errors"]
        assert "tsc_failed" in " ".join(result["data_warnings"])

    def test_escomplex_not_available(self, tmp_path, monkeypatch):
        """analyze_file when escomplex is not installed."""
        f = tmp_path / "test.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer(escomplex=None)

        monkeypatch.setattr(
            analyzer, "_run_eslint", lambda paths: {str(f): {"lint_violations": 0}}
        )
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: {str(f): 0})

        result = analyzer.analyze_file(f)
        assert result["maintainability_index"] is None
        assert "no_escomplex" in " ".join(result["data_warnings"])

    def test_escomplex_fails(self, tmp_path, monkeypatch):
        """analyze_file when escomplex returns None (parse error)."""
        f = tmp_path / "test.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()

        monkeypatch.setattr(
            analyzer, "_run_eslint", lambda paths: {str(f): {"lint_violations": 0}}
        )
        monkeypatch.setattr(analyzer, "_run_tsc", lambda paths: {str(f): 0})
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        result = analyzer.analyze_file(f)
        assert "escomplex" in result["tool_errors"]
        assert "escomplex_failed" in " ".join(result["data_warnings"])


# ===================================================================
# analyze_batch additional coverage
# ===================================================================


class TestAnalyzeBatchCoverage:
    def _make_analyzer(self, **tool_versions) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {
            "node": "node",
            "eslint": "eslint",
            "tsc": None,
            "escomplex": "escomplex",
            **tool_versions,
        }
        return analyzer

    def test_empty_paths_returns_empty(self):
        """analyze_batch([]) returns []."""
        analyzer = self._make_analyzer()
        assert analyzer.analyze_batch([]) == []

    def test_no_tsc_sets_warning(self, tmp_path, monkeypatch):
        """Batch with no tsc installed sets no_tsc warning."""
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer(tsc=None)

        eslint = {str(f): {"lint_violations": 0}}
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: eslint)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        results = analyzer.analyze_batch([f])
        assert "no_tsc" in " ".join(results[0]["data_warnings"])

    def test_escomplex_success_in_batch(self, tmp_path, monkeypatch):
        """Batch with escomplex returning valid data."""
        f = tmp_path / "a.ts"
        f.write_text("function foo() { return 1; }\n")
        analyzer = self._make_analyzer()

        eslint = {str(f): {"lint_violations": 0}}
        esc = {"cyclomatic": 2, "avg_cyclomatic": 1.0, "maintainability": 90.0}
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: eslint)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: esc)

        results = analyzer.analyze_batch([f])
        assert results[0]["cyclomatic_complexity"] == 2
        assert results[0]["maintainability_index"] == 90.0

    def test_escomplex_failure_in_batch(self, tmp_path, monkeypatch):
        """Batch with escomplex returning None sets tool_error."""
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer()

        eslint = {str(f): {"lint_violations": 0}}
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: eslint)
        monkeypatch.setattr(analyzer, "_run_escomplex", lambda path: None)

        results = analyzer.analyze_batch([f])
        assert "escomplex" in results[0]["tool_errors"]
        assert "escomplex_failed" in " ".join(results[0]["data_warnings"])

    def test_no_escomplex_in_batch(self, tmp_path, monkeypatch):
        """Batch with no escomplex installed sets no_escomplex warning."""
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        analyzer = self._make_analyzer(escomplex=None)

        eslint = {str(f): {"lint_violations": 0}}
        monkeypatch.setattr(analyzer, "_run_eslint", lambda paths: eslint)

        results = analyzer.analyze_batch([f])
        assert "no_escomplex" in " ".join(results[0]["data_warnings"])


# ===================================================================
# _run_eslint error branches
# ===================================================================


class TestEslintErrors:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {"node": "node", "eslint": "eslint"}
        return analyzer

    def test_timeout_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 60)

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_eslint([Path("/tmp/a.ts")]) is None

    def test_json_decode_error_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="not valid json", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_eslint([Path("/tmp/a.ts")]) is None

    def test_general_exception_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise OSError("eslint binary corrupted")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_eslint([Path("/tmp/a.ts")]) is None

    def test_security_medium_severity(self, monkeypatch):
        """Security rule with severity 1 counts as medium."""
        eslint_output = json.dumps(
            [
                {
                    "filePath": "/tmp/a.ts",
                    "messages": [
                        {
                            "ruleId": "security/detect-eval-with-expression",
                            "severity": 1,
                            "message": "eval",
                        },
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
        result = analyzer._run_eslint([Path("/tmp/a.ts")])
        assert result["/tmp/a.ts"]["security_medium"] == 1
        assert result["/tmp/a.ts"]["security_high"] == 0

    def test_cognitive_complexity_parsing(self, monkeypatch):
        """sonarjs/cognitive-complexity message parsed for value."""
        eslint_output = json.dumps(
            [
                {
                    "filePath": "/tmp/a.ts",
                    "messages": [
                        {
                            "ruleId": "sonarjs/cognitive-complexity",
                            "severity": 2,
                            "message": "Refactor this function (complexity is 42).",
                        },
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
        result = analyzer._run_eslint([Path("/tmp/a.ts")])
        assert result["/tmp/a.ts"]["cognitive_complexity"] == 42


# ===================================================================
# _run_tsc project mode and edge cases
# ===================================================================


class TestTscProjectMode:
    def _make_analyzer(self, project_root=None) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = project_root
        analyzer._tool_versions = {"node": "node", "eslint": "eslint", "tsc": "tsc"}
        return analyzer

    def test_with_tsconfig_uses_project_flag(self, tmp_path, monkeypatch):
        """When tsconfig.json exists, tsc uses --project flag."""
        (tmp_path / "tsconfig.json").write_text("{}")
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")
        captured_cmds: list[list[str]] = []

        def mock_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            # --listFiles call returns the file as in-scope
            if "--listFiles" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=str(f.resolve()) + "\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(project_root=tmp_path)
        result = analyzer._run_tsc([f])

        assert result is not None
        assert "--project" in captured_cmds[0]
        assert result[str(f)] == 0

    def test_project_mode_out_of_scope_returns_none(self, tmp_path, monkeypatch):
        """In project mode, files not in tsconfig scope get None."""
        (tmp_path / "tsconfig.json").write_text("{}")
        f = tmp_path / "a.ts"
        f.write_text("const x = 1;\n")

        def mock_run(cmd, **kwargs):
            # --listFiles returns empty (file not in scope)
            if "--listFiles" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(project_root=tmp_path)
        result = analyzer._run_tsc([f])

        assert result is not None
        assert result[str(f)] is None  # not in scope = unchecked

    def test_without_tsconfig_uses_strict(self, tmp_path, monkeypatch):
        """Without tsconfig.json, tsc uses --strict with explicit files."""
        captured_cmds: list[list[str]] = []

        def mock_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer(project_root=tmp_path)
        f = tmp_path / "a.ts"
        analyzer._run_tsc([f])

        assert "--strict" in captured_cmds[0]
        assert str(f) in captured_cmds[0]

    def test_general_exception_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise OSError("tsc binary missing")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_tsc([Path("/tmp/a.ts")]) is None


# ===================================================================
# _run_escomplex exception branches
# ===================================================================


class TestEscomplexExceptions:
    def _make_analyzer(self) -> TypeScriptAnalyzer:
        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer._tool_versions = {"escomplex": "escomplex"}
        return analyzer

    def test_timeout_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_escomplex(Path("/tmp/a.ts")) is None

    def test_general_exception_returns_none(self, monkeypatch):
        def mock_run(cmd, **kwargs):
            raise OSError("node binary missing")

        monkeypatch.setattr(subprocess, "run", mock_run)
        analyzer = self._make_analyzer()
        assert analyzer._run_escomplex(Path("/tmp/a.ts")) is None


# ===================================================================
# check_tools optional tool branches
# ===================================================================


class TestCheckToolsBranches:
    def test_tsc_found_optional(self, monkeypatch):
        """tsc found via shutil.which registers in results."""

        def fake_which(name, **kwargs):
            if name in ("node", "eslint", "tsc"):
                return f"/usr/bin/{name}"
            return None

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(
            TypeScriptAnalyzer, "_check_npm_package", staticmethod(lambda p: False)
        )
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", True)

        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        result = analyzer.check_tools()
        assert result["tsc"] == "tsc"
        assert result["escomplex"] is None

        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)

    def test_escomplex_missing_prints_warning(self, monkeypatch, capsys):
        """Missing optional tools print warning."""

        def fake_which(name, **kwargs):
            if name in ("node", "eslint"):
                return f"/usr/bin/{name}"
            return None

        monkeypatch.setattr(shutil, "which", fake_which)
        monkeypatch.setattr(
            TypeScriptAnalyzer, "_check_npm_package", staticmethod(lambda p: False)
        )
        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", True)

        analyzer = object.__new__(TypeScriptAnalyzer)
        analyzer.project_root = None
        analyzer.check_tools()

        captured = capsys.readouterr()
        assert "optional" in captured.out.lower()
        assert "tsc" in captured.out or "escomplex" in captured.out

        monkeypatch.setattr(TypeScriptAnalyzer, "_path_ensured", False)
