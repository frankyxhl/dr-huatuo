"""TypeScript/TSX language analyzer — implements the LanguageAnalyzer protocol."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from dr_huatuo.analyzers.base import BaseAnalyzer, ToolNotFoundError


class TypeScriptAnalyzer(BaseAnalyzer):
    """Analyzer for TypeScript files (.ts, .tsx).

    Uses Node.js-based tools (eslint, tsc, escomplex) via subprocess.
    Overrides analyze_batch() for batch processing to avoid per-file
    Node.js startup overhead.
    """

    name: ClassVar[str] = "typescript"
    extensions: ClassVar[list[str]] = [".ts", ".tsx"]
    critical_tools: ClassVar[list[str]] = ["node", "eslint"]
    optional_tools: ClassVar[list[str]] = ["tsc", "escomplex"]
    _path_ensured: ClassVar[bool] = False

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = self._find_config_root(project_root)
        self._ensure_node_on_path()
        self._tool_versions = self.check_tools()

    @staticmethod
    def _find_config_root(start: Path | None) -> Path | None:
        """Walk up from start to find directory with tsconfig.json or eslint config."""
        if start is None:
            return None
        p = Path(start).resolve()
        if p.is_file():
            p = p.parent
        config_names = [
            "tsconfig.json",
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            ".eslintrc.yml",
            "eslint.config.js",
            "eslint.config.mjs",
        ]
        for d in [p, *p.parents]:
            if any((d / name).exists() for name in config_names):
                return d
            if (d / ".git").exists():
                return d  # stop at repo root
        return p  # fallback to original

    @classmethod
    def _ensure_node_on_path(cls) -> None:
        """Add common Node.js bin dirs to PATH (runs once per process)."""
        if cls._path_ensured:
            return
        extra_dirs = []
        # npm global bin
        try:
            result = subprocess.run(
                ["npm", "bin", "-g"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                extra_dirs.append(result.stdout.strip())
        except Exception:
            pass
        # Also add Python venv bin for consistency
        extra_dirs.append(str(Path(sys.executable).parent))

        path = os.environ.get("PATH", "")
        for d in extra_dirs:
            if d not in path.split(os.pathsep):
                path = d + os.pathsep + path
        os.environ["PATH"] = path
        cls._path_ensured = True

    def check_tools(self) -> dict[str, str | None]:
        """Check tool availability. Raise for missing critical tools."""
        results: dict[str, str | None] = {}
        missing_critical = []
        missing_optional = []

        for tool in self.critical_tools:
            if shutil.which(tool) is not None:
                results[tool] = tool
            else:
                results[tool] = None
                missing_critical.append(tool)

        for tool in self.optional_tools:
            if tool == "escomplex":
                # escomplex is an npm package, not a binary
                found = self._check_npm_package("typhonjs-escomplex")
                results[tool] = "escomplex" if found else None
                if not found:
                    missing_optional.append(tool)
            else:
                if shutil.which(tool) is not None:
                    results[tool] = tool
                else:
                    results[tool] = None
                    missing_optional.append(tool)

        if missing_critical:
            raise ToolNotFoundError(
                f"Critical tools not found: {', '.join(missing_critical)}. "
                f"Install with: npm install -g {' '.join(missing_critical)}"
            )

        if missing_optional:
            print(
                "Warning: optional TS tools not installed: "
                f"{', '.join(missing_optional)}"
            )

        return results

    @staticmethod
    def _check_npm_package(package: str) -> bool:
        """Check if an npm package is available.

        Only accepts valid npm package names to prevent code injection.
        """
        if not re.match(r"^[a-z0-9@][a-z0-9_./@-]*$", package):
            return False
        try:
            result = subprocess.run(
                ["node", "-e", f"require('{package}')"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def analyze_file(self, path: Path) -> dict:
        """Analyze a single TypeScript file and return the standard metric dict."""
        path = Path(path)
        source = path.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        loc = len(lines)

        data_warnings: list[str] = []
        tool_errors: dict[str, str] = {}

        # --- eslint ---
        lint_violations = 0
        security_high = None
        security_medium = None
        cognitive_complexity = None
        eslint_data = self._run_eslint([path])
        if eslint_data is not None:
            file_results = eslint_data.get(str(path), {})
            lint_violations = file_results.get("lint_violations", 0)
            security_high = file_results.get("security_high")
            security_medium = file_results.get("security_medium")
            cognitive_complexity = file_results.get("cognitive_complexity")
        else:
            tool_errors["eslint"] = "eslint failed or not configured"
            data_warnings.append("eslint_failed: lint metrics unavailable")

        # --- tsc ---
        type_errors = None
        if self._tool_versions.get("tsc"):
            tsc_data = self._run_tsc([path])
            if tsc_data is not None:
                type_errors = tsc_data.get(str(path))
            else:
                tool_errors["tsc"] = "tsc failed"
                data_warnings.append("tsc_failed: type checking unavailable")
        else:
            data_warnings.append("no_tsc: type checking unavailable")

        # --- escomplex ---
        cyclomatic_complexity = None
        avg_complexity = None
        maintainability_index = None
        if self._tool_versions.get("escomplex"):
            esc_data = self._run_escomplex(path)
            if esc_data is not None:
                cyclomatic_complexity = esc_data.get("cyclomatic")
                avg_complexity = esc_data.get("avg_cyclomatic")
                maintainability_index = esc_data.get("maintainability")
            else:
                tool_errors["escomplex"] = "escomplex failed"
                data_warnings.append("escomplex_failed: complexity metrics unavailable")
        else:
            data_warnings.append("no_escomplex: MI/complexity unavailable")

        # --- Text-based metrics ---
        function_count = self._count_functions(source)
        class_count = self._count_classes(source)
        comment_density = self._comment_density(source, loc)
        docstring_density = self._jsdoc_density(source, function_count)
        max_nesting_depth = self._nesting_depth(source)

        return self._build_result(
            cyclomatic_complexity=cyclomatic_complexity,
            avg_complexity=avg_complexity,
            cognitive_complexity=cognitive_complexity,
            max_nesting_depth=max_nesting_depth,
            loc=loc,
            function_count=function_count,
            class_count=class_count,
            maintainability_index=maintainability_index,
            comment_density=comment_density,
            docstring_density=docstring_density,
            lint_violations=lint_violations,
            security_high=security_high,
            security_medium=security_medium,
            type_errors=type_errors,
            data_warnings=data_warnings,
            tool_errors=tool_errors,
        )

    def analyze_batch(self, paths: list[Path]) -> list[dict]:
        """Batch analyze: run eslint/tsc once on all files, split results."""
        if not paths:
            return []

        paths = [Path(p) for p in paths]

        # Batch eslint — keep None distinct from {} (tool ran but found nothing)
        eslint_data = self._run_eslint(paths)
        eslint_failed = eslint_data is None
        if eslint_failed:
            eslint_data = {}

        # Batch tsc — same distinction
        tsc_data = None
        tsc_failed = False
        if self._tool_versions.get("tsc"):
            tsc_data = self._run_tsc(paths)
            tsc_failed = tsc_data is None
            if tsc_failed:
                tsc_data = {}

        results = []
        for path in paths:
            source = path.read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            loc = len(lines)
            data_warnings: list[str] = []
            tool_errors: dict[str, str] = {}

            # eslint results
            if eslint_failed:
                lint_violations = 0
                security_high = None
                security_medium = None
                cognitive_complexity = None
                tool_errors["eslint"] = "eslint failed or not configured"
                data_warnings.append("eslint_failed: lint metrics unavailable")
            else:
                file_eslint = eslint_data.get(str(path), {})  # type: ignore[union-attr]
                lint_violations = file_eslint.get("lint_violations", 0)
                security_high = file_eslint.get("security_high")
                security_medium = file_eslint.get("security_medium")
                cognitive_complexity = file_eslint.get("cognitive_complexity")

            # tsc results
            type_errors = None
            if tsc_failed:
                tool_errors["tsc"] = "tsc failed"
                data_warnings.append("tsc_failed: type checking unavailable")
            elif tsc_data is not None:
                type_errors = tsc_data.get(str(path))
            elif not self._tool_versions.get("tsc"):
                data_warnings.append("no_tsc: type checking unavailable")

            # escomplex (per-file, no batch mode)
            cyclomatic_complexity = None
            avg_complexity = None
            maintainability_index = None
            if self._tool_versions.get("escomplex"):
                esc_data = self._run_escomplex(path)
                if esc_data:
                    cyclomatic_complexity = esc_data.get("cyclomatic")
                    avg_complexity = esc_data.get("avg_cyclomatic")
                    maintainability_index = esc_data.get("maintainability")
                else:
                    tool_errors["escomplex"] = "escomplex failed"
                    data_warnings.append(
                        "escomplex_failed: complexity metrics unavailable"
                    )
            else:
                data_warnings.append("no_escomplex: MI/complexity unavailable")

            function_count = self._count_functions(source)
            class_count = self._count_classes(source)
            comment_density = self._comment_density(source, loc)
            docstring_density = self._jsdoc_density(source, function_count)
            max_nesting_depth = self._nesting_depth(source)

            results.append(
                self._build_result(
                    cyclomatic_complexity=cyclomatic_complexity,
                    avg_complexity=avg_complexity,
                    cognitive_complexity=cognitive_complexity,
                    max_nesting_depth=max_nesting_depth,
                    loc=loc,
                    function_count=function_count,
                    class_count=class_count,
                    maintainability_index=maintainability_index,
                    comment_density=comment_density,
                    docstring_density=docstring_density,
                    lint_violations=lint_violations,
                    security_high=security_high,
                    security_medium=security_medium,
                    type_errors=type_errors,
                    data_warnings=data_warnings,
                    tool_errors=tool_errors,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Shared result builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(
        *,
        cyclomatic_complexity: int | None,
        avg_complexity: float | None,
        cognitive_complexity: int | None,
        max_nesting_depth: int,
        loc: int,
        function_count: int,
        class_count: int,
        maintainability_index: float | None,
        comment_density: float,
        docstring_density: float,
        lint_violations: int,
        security_high: int | None,
        security_medium: int | None,
        type_errors: int | None,
        data_warnings: list[str],
        tool_errors: dict[str, str],
    ) -> dict:
        """Build the standard metric dict from computed values."""
        return {
            # Complexity
            "cyclomatic_complexity": cyclomatic_complexity,
            "avg_complexity": avg_complexity,
            "cognitive_complexity": cognitive_complexity,
            "max_nesting_depth": max_nesting_depth,
            # Volume
            "loc": loc,
            "function_count": function_count,
            "class_count": class_count,
            # Readability
            "maintainability_index": maintainability_index,
            "comment_density": comment_density,
            "docstring_density": docstring_density,
            # Code style
            "lint_violations": lint_violations,
            "linter_score": None,
            # Security
            "security_high": security_high,
            "security_medium": security_medium,
            # Type safety
            "type_errors": type_errors,
            # Halstead — not available for TS
            "n1": None,
            "n2": None,
            "N1": None,
            "N2": None,
            "halstead_volume": None,
            "halstead_difficulty": None,
            "halstead_effort": None,
            # Metadata
            "language": "typescript",
            "data_warnings": data_warnings,
            "error_type": "tool_error" if tool_errors else None,
            "error_detail": "; ".join(tool_errors.values()) if tool_errors else None,
            "tool_errors": tool_errors or None,
            # Legacy compat (quality_profile reads these with fallback)
            "ruff_violations": lint_violations,
            "pylint_score": None,
            "bandit_high": security_high,
            "bandit_medium": security_medium,
            "mypy_errors": type_errors,
        }

    # ------------------------------------------------------------------
    # Tool runners
    # ------------------------------------------------------------------

    def _run_eslint(self, paths: list[Path]) -> dict[str, dict] | None:
        """Run eslint on files, return per-file metrics dict."""
        try:
            cmd = ["eslint", "--format", "json", "--no-error-on-unmatched-pattern"]
            # Use project root for config resolution; if no config found,
            # eslint will use its default or the user's global config
            cmd.extend(str(p) for p in paths)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root) if self.project_root else None,
            )
            # eslint exits 1 when violations found — check for valid JSON
            if not result.stdout.strip():
                if result.returncode not in (0, 1):
                    return None  # eslint crashed or config error
                return {}  # genuinely no files matched
            data = json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return None
        except json.JSONDecodeError:
            return None
        except Exception:
            return None

        per_file: dict[str, dict] = {}
        for entry in data:
            fpath = entry.get("filePath", "")
            messages = entry.get("messages", [])

            lint_count = 0
            sec_high = 0
            sec_med = 0
            cog = None

            for msg in messages:
                rule = msg.get("ruleId") or ""
                severity = msg.get("severity", 0)

                if rule.startswith("security/"):
                    if severity >= 2:
                        sec_high += 1
                    else:
                        sec_med += 1
                elif rule == "sonarjs/cognitive-complexity":
                    # Extract complexity from message if available
                    match = re.search(r"(\d+)", msg.get("message", ""))
                    if match:
                        val = int(match.group(1))
                        cog = max(cog or 0, val)
                else:
                    lint_count += 1

            per_file[fpath] = {
                "lint_violations": lint_count,
                "security_high": sec_high,
                "security_medium": sec_med,
                "cognitive_complexity": cog,
            }

        return per_file

    def _run_tsc(self, paths: list[Path]) -> dict[str, int | None] | None:
        """Run tsc --noEmit, return {filepath: error_count or None}."""
        try:
            cmd = ["tsc", "--noEmit", "--pretty", "false"]
            if self.project_root:
                tsconfig = Path(self.project_root) / "tsconfig.json"
                if tsconfig.exists():
                    cmd.extend(["--project", str(tsconfig)])
                else:
                    cmd.append("--strict")
                    cmd.extend(str(p) for p in paths)
            else:
                cmd.append("--strict")
                cmd.extend(str(p) for p in paths)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root) if self.project_root else None,
            )

            if result.returncode == 0:
                return {str(p): 0 for p in paths}

            # Default to 0 (clean) — only files with errors get incremented
            per_file: dict[str, int | None] = {str(p): 0 for p in paths}
            for line in result.stdout.splitlines():
                # Format: file.ts(line,col): error TS1234: message
                match = re.match(r"(.+?)\(\d+,\d+\):\s+error\s+", line)
                if match:
                    fpath = match.group(1)
                    for p in paths:
                        if str(p).endswith(fpath) or fpath.endswith(str(p.name)):
                            per_file[str(p)] = (per_file.get(str(p)) or 0) + 1
                            break
            return per_file
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    def _run_escomplex(self, path: Path) -> dict | None:
        """Run escomplex on a single file, return complexity metrics."""
        try:
            script = (
                "const escomplex = require('typhonjs-escomplex');"
                "const fs = require('fs');"
                "const src = fs.readFileSync(process.argv[1], 'utf8');"
                "try {"
                "  const r = escomplex.analyzeModule(src);"
                "  console.log(JSON.stringify({"
                "    cyclomatic: r.aggregate.cyclomatic,"
                "    avg_cyclomatic: r.methodAverage.cyclomatic,"
                "    maintainability: r.maintainability"
                "  }));"
                "} catch(e) {"
                "  console.log(JSON.stringify({error: e.message}));"
                "}"
            )
            result = subprocess.run(
                ["node", "-e", script, str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.project_root) if self.project_root else None,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            if "error" in data:
                return None
            return {
                "cyclomatic": data.get("cyclomatic"),
                "avg_cyclomatic": round(data.get("avg_cyclomatic", 0), 1),
                "maintainability": round(data.get("maintainability", 0), 1),
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Text-based metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _count_functions(source: str) -> int:
        """Count function declarations and arrow functions."""
        patterns = [
            r"\bfunction\s+\w+\s*\(",  # function declarations
            r"\bfunction\s*\(",  # anonymous functions
            r"=>\s*[{(]",  # arrow functions
        ]
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, source))
        return count

    @staticmethod
    def _count_classes(source: str) -> int:
        """Count class declarations."""
        return len(re.findall(r"\bclass\s+\w+", source))

    @staticmethod
    def _comment_density(source: str, loc: int) -> float:
        """Calculate comment line density."""
        if loc == 0:
            return 0.0
        comment_lines = 0
        in_block = False
        for line in source.splitlines():
            stripped = line.strip()
            if in_block:
                comment_lines += 1
                if "*/" in stripped:
                    in_block = False
            elif stripped.startswith("//"):
                comment_lines += 1
            elif stripped.startswith("/*"):
                comment_lines += 1
                if "*/" not in stripped:
                    in_block = True
        return round(comment_lines / loc, 4)

    @staticmethod
    def _jsdoc_density(source: str, function_count: int) -> float:
        """Calculate JSDoc coverage: JSDoc blocks / function count."""
        if function_count == 0:
            return 0.0
        jsdoc_count = len(re.findall(r"/\*\*[\s\S]*?\*/", source))
        return round(min(jsdoc_count / function_count, 1.0), 4)

    @staticmethod
    def _nesting_depth(source: str) -> int:
        """Estimate max nesting depth from brace counting."""
        max_depth = 0
        current = 0
        for ch in source:
            if ch == "{":
                current += 1
                max_depth = max(max_depth, current)
            elif ch == "}":
                current = max(0, current - 1)
        # Subtract 1 for module/class/function wrapper level
        return max(0, max_depth - 1)
