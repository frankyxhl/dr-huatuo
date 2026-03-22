"""
Dataset annotation pipeline for Python code quality analysis.

Runs multiple static analysis tools (ruff, radon, bandit, mypy, pylint)
with isolation flags to produce per-file quality records in JSONL format,
structured for downstream ML training or dataset curation.

Tools are invoked directly via subprocess (not via CodeAnalyzer) for
research-grade control: per-tool isolation, timeout, and error tracking.
"""

import ast
import hashlib
import json
import platform
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Iterator, Optional

from dr_huatuo.quality_profile import profile_file

SCHEMA_VERSION = "1.0"
ANNOTATOR_VERSION = "0.1.0"

# Control-flow node types for nesting depth calculation
_CONTROL_FLOW_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncFor,
    ast.AsyncWith,
)


# ===================================================================
# Standalone scoring functions (reimplemented from CodeAnalyzer)
# ===================================================================


def _calculate_score(
    ruff_violations: int = 0,
    cyclomatic_complexity: int = 0,
    bandit_high: int = 0,
    bandit_medium: int = 0,
    mypy_errors: int = 0,
) -> float:
    """Calculate quality score (0-100).

    Scoring rules (same as CodeAnalyzer._calculate_score):
      - Ruff violations: -2 each, capped at 30
      - Complexity >10: (cc - 10) * 5, capped at 20
      - Bandit HIGH: -15 each, capped at 30
      - Bandit MEDIUM: -5 each, capped at 15
      - Mypy errors: -1 each, capped at 10
      - Floor at 0
    """
    score = 100.0
    score -= min(ruff_violations * 2, 30)
    if cyclomatic_complexity > 10:
        score -= min((cyclomatic_complexity - 10) * 5, 20)
    score -= min(bandit_high * 15, 30)
    score -= min(bandit_medium * 5, 15)
    score -= min(mypy_errors, 10)
    return max(score, 0.0)


def _get_grade(score: float) -> str:
    """Get grade label from score.

    Returns English-labeled grade strings matching CodeAnalyzer._get_grade.
    """
    if score >= 90:
        return "A (Excellent)"
    elif score >= 80:
        return "B (Good)"
    elif score >= 70:
        return "C (Fair)"
    elif score >= 60:
        return "D (Pass)"
    else:
        return "F (Fail)"


# ===================================================================
# Source normalization
# ===================================================================


def _normalize_source(source: str) -> str:
    """Normalize source for content_sha256.

    Converts CRLF to LF and strips trailing whitespace per line.
    """
    if not source:
        return ""
    source = source.replace("\r\n", "\n")
    lines = source.split("\n")
    lines = [line.rstrip() for line in lines]
    return "\n".join(lines)


# ===================================================================
# AST metric helpers
# ===================================================================


def _count_classes(tree: ast.AST) -> int:
    """Count all ClassDef nodes (top-level and nested)."""
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))


def _max_nesting_depth(tree: ast.AST) -> int:
    """Calculate maximum nesting depth of control-flow blocks.

    Function/class bodies are depth 0. Each nested control-flow
    keyword (if, for, while, try, with, async for, async with) adds 1.
    """
    max_depth = 0

    def _walk(node: ast.AST, depth: int) -> None:
        nonlocal max_depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _CONTROL_FLOW_NODES):
                new_depth = depth + 1
                if new_depth > max_depth:
                    max_depth = new_depth
                _walk(child, new_depth)
            elif isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                # Reset depth for function/class bodies
                _walk(child, 0)
            else:
                _walk(child, depth)

    _walk(tree, 0)
    return max_depth


def _fanout_modules(tree: ast.AST) -> int:
    """Count distinct module names from import statements."""
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return len(modules)


def _fanout_symbols(tree: ast.AST) -> int:
    """Count distinct imported symbols from 'from X import y' statements."""
    symbols = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                symbols.add((node.module or "", alias.name))
    return len(symbols)


def _comment_density(source: str, loc: int) -> float:
    """Calculate comment_density = comment_lines / loc.

    Comment lines: first non-whitespace is '#', excluding shebangs
    (#! on line 1) and encoding cookies (# -*- coding).
    """
    if loc == 0:
        return 0.0
    lines = source.splitlines()
    comment_count = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        # Exclude shebang on line 1
        if i == 0 and stripped.startswith("#!"):
            continue
        # Exclude encoding cookies
        if "coding" in stripped and ("-*-" in stripped or "coding:" in stripped):
            continue
        comment_count += 1
    return comment_count / loc


def _docstring_density(tree: ast.AST) -> tuple[float, int]:
    """Calculate docstring_density = functions_with_docstring / function_count.

    Returns (density, function_count).
    """
    func_count = 0
    doc_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_count += 1
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                doc_count += 1
    if func_count == 0:
        return 0.0, 0
    return doc_count / func_count, func_count


# ===================================================================
# Module-level worker for multiprocessing (must be picklable)
# ===================================================================


def _annotate_file_worker(args: tuple) -> dict:
    """Module-level worker function for ProcessPoolExecutor.

    Args:
        args: Tuple of (annotator_kwargs, path, source, license_str).
              annotator_kwargs is used to reconstruct a DatasetAnnotator
              in the worker process.

    Returns:
        Annotation dict.
    """
    annotator_kwargs, path, source, license_str = args
    ann = DatasetAnnotator(**annotator_kwargs)
    return ann.annotate_file(path, source=source, license=license_str)


# ===================================================================
# DatasetAnnotator
# ===================================================================


class DatasetAnnotator:
    """Batch annotation pipeline for Python code datasets.

    Runs static analysis tools directly via subprocess with isolation
    flags. Does NOT delegate to CodeAnalyzer.
    """

    def __init__(
        self,
        venv_python: Optional[str] = None,
        run_pylint: bool = True,
        full: bool = False,
        workers: int = 1,
        tool_timeout: int = 30,
        isolated: bool = True,
    ):
        self.venv_python = venv_python
        self.run_pylint = run_pylint
        self.full = full
        self.workers = workers
        self.tool_timeout = tool_timeout
        self.isolated = isolated
        self.tool_versions: dict[str, str] = {}

        self._check_tools()
        self._capture_tool_versions()

    def _check_tools(self) -> None:
        """Verify required tools are available. Raise if missing."""
        required = ["ruff", "radon", "bandit", "mypy", "complexipy"]
        if self.run_pylint:
            required.append("pylint")

        missing = []
        for tool in required:
            if shutil.which(tool) is None:
                missing.append(tool)

        if missing:
            raise RuntimeError(
                f"Required tools not found: {', '.join(missing)}. "
                f"Install with: pip install {' '.join(missing)}"
            )

    def _capture_tool_versions(self) -> None:
        """Capture version strings for all tools."""
        tools_cmds = {
            "ruff": ["ruff", "--version"],
            "radon": ["radon", "--version"],
            "bandit": ["bandit", "--version"],
            "mypy": ["mypy", "--version"],
            "complexipy": ["complexipy", "--version"],
        }
        if self.run_pylint:
            tools_cmds["pylint"] = ["pylint", "--version"]

        for name, cmd in tools_cmds.items():
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                version_str = result.stdout.strip().split("\n")[0]
                # Extract version number from output
                match = re.search(r"[\d]+\.[\d]+\.[\d]+", version_str)
                if match:
                    self.tool_versions[name] = match.group(0)
                else:
                    self.tool_versions[name] = version_str
            except Exception:
                self.tool_versions[name] = "unknown"

    def _runtime_env(self) -> dict:
        """Build runtime_env metadata block."""
        return {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "isolated": self.isolated,
        }

    def _analysis_config(self) -> dict:
        """Build analysis_config metadata block."""
        return {
            "run_pylint": self.run_pylint,
            "full": self.full,
            "tool_timeout": self.tool_timeout,
        }

    def _null_record(
        self,
        path: str,
        source: str,
        license_: str,
        content_sha256: Optional[str],
        error_type: str,
        error_detail: str,
    ) -> dict:
        """Build a record where all metric fields are null (file-level error)."""
        record: dict = {
            "schema_version": SCHEMA_VERSION,
            "annotator_version": ANNOTATOR_VERSION,
            "tool_versions": dict(self.tool_versions),
            "analysis_config": self._analysis_config(),
            "runtime_env": self._runtime_env(),
            "path": path,
            "content_sha256": content_sha256,
            "source": source,
            "license": license_,
            "score": None,
            "grade": None,
            "ruff_violations": None,
            "bandit_high": None,
            "bandit_medium": None,
            "mypy_errors": None,
            "pylint_score": None,
            "loc": None,
            "function_count": None,
            "class_count": None,
            "cyclomatic_complexity": None,
            "avg_complexity": None,
            "cognitive_complexity": None,
            "max_nesting_depth": None,
            "n1": None,
            "n2": None,
            "N1": None,
            "N2": None,
            "halstead_volume": None,
            "halstead_difficulty": None,
            "halstead_effort": None,
            "maintainability_index": None,
            "fanout_modules": None,
            "fanout_symbols": None,
            "comment_density": None,
            "docstring_density": None,
            "data_warnings": [],
            "tool_errors": None,
            "error_type": error_type,
            "error_detail": error_detail,
        }
        return record

    # ---------------------------------------------------------------
    # Layer 1: Tool subprocess runners (with isolation flags)
    # ---------------------------------------------------------------

    def _run_ruff(self, path: str) -> tuple[Optional[int], Optional[str]]:
        """Run ruff check with isolation. Returns (violation_count, error_reason)."""
        cmd = ["ruff", "check", path, "--output-format=json"]
        if self.isolated:
            cmd.append("--isolated")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                return len(data), None
            return 0, None
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except Exception:
            return None, "crash"

    def _run_radon_cc_subprocess(
        self, path: str
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Run radon cc via subprocess. Returns (max_cc, func_count, error_reason)."""
        cmd = ["radon", "cc", path, "-j"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                all_funcs = []
                for _fp, funcs in data.items():
                    all_funcs.extend(funcs)
                if all_funcs:
                    complexities = [f.get("complexity", 0) for f in all_funcs]
                    return max(complexities), len(all_funcs), None
            return 0, 0, None
        except subprocess.TimeoutExpired:
            return None, None, "timeout"
        except Exception:
            return None, None, "crash"

    def _run_bandit(
        self, path: str
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Run bandit with isolation.

        Returns (high_count, medium_count, error_reason).
        """
        cmd = ["bandit", "-r", path, "-f", "json"]
        if self.isolated:
            cmd.extend(["-c", "/dev/null"])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                results = data.get("results", [])
                high = sum(1 for r in results if r.get("issue_severity") == "HIGH")
                medium = sum(1 for r in results if r.get("issue_severity") == "MEDIUM")
                return high, medium, None
            return 0, 0, None
        except subprocess.TimeoutExpired:
            return None, None, "timeout"
        except Exception:
            return None, None, "crash"

    def _run_mypy(self, path: str) -> tuple[Optional[int], Optional[str]]:
        """Run mypy with isolation. Returns (error_count, error_reason)."""
        cmd = [
            "mypy",
            path,
            "--output=json",
            "--no-error-summary",
        ]
        if self.isolated:
            cmd.append("--config-file=/dev/null")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )
            errors = 0
            for line in result.stdout.strip().split("\n"):
                if line and line.startswith("{"):
                    try:
                        json.loads(line)
                        errors += 1
                    except json.JSONDecodeError:
                        pass
            return errors, None
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except Exception:
            return None, "crash"

    def _run_pylint(self, path: str) -> tuple[Optional[float], Optional[str]]:
        """Run pylint with isolation. Returns (score, error_reason)."""
        cmd = ["pylint", path, "--output-format=parseable"]
        if self.isolated:
            cmd.append("--rcfile=/dev/null")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )
            output = result.stdout + result.stderr
            match = re.search(r"rated at ([\d.]+)/10", output)
            if match:
                return float(match.group(1)), None
            return 0.0, None
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except Exception:
            return None, "crash"

    # ---------------------------------------------------------------
    # Layer 2: In-process analysis (radon Python API, complexipy, AST)
    # ---------------------------------------------------------------

    def _layer2_radon(self, source: str) -> dict:
        """Compute radon-based in-process metrics."""
        result: dict = {
            "avg_complexity": None,
            "maintainability_index": None,
            "n1": None,
            "n2": None,
            "N1": None,
            "N2": None,
            "halstead_volume": None,
            "halstead_difficulty": None,
            "halstead_effort": None,
        }
        try:
            from radon.complexity import cc_visit
            from radon.metrics import h_visit, mi_visit

            # Average complexity
            cc_results = cc_visit(source)
            if cc_results:
                total = sum(f.complexity for f in cc_results)
                result["avg_complexity"] = round(total / len(cc_results), 2)
            else:
                result["avg_complexity"] = 0.0

            # Maintainability index
            mi = mi_visit(source, True)
            result["maintainability_index"] = round(mi, 1) if mi is not None else None

            # Halstead metrics
            h = h_visit(source)
            if h and h.total:
                t = h.total
                result["n1"] = t.h1
                result["n2"] = t.h2
                result["N1"] = t.N1
                result["N2"] = t.N2
                result["halstead_volume"] = round(t.volume, 1) if t.volume else 0.0
                result["halstead_difficulty"] = (
                    round(t.difficulty, 1) if t.difficulty else 0.0
                )
                result["halstead_effort"] = round(t.effort, 1) if t.effort else 0.0
            else:
                result["n1"] = 0
                result["n2"] = 0
                result["N1"] = 0
                result["N2"] = 0
                result["halstead_volume"] = 0.0
                result["halstead_difficulty"] = 0.0
                result["halstead_effort"] = 0.0

        except Exception:
            pass  # Leave as None
        return result

    def _layer2_complexipy(self, path: str) -> Optional[int]:
        """Compute cognitive complexity using complexipy."""
        try:
            from complexipy import file_complexity

            fc = file_complexity(path)
            return fc.complexity
        except Exception:
            return None

    def _layer2_ast(self, source: str, tree: ast.AST) -> dict:
        """Compute AST-based metrics."""
        loc = len(source.splitlines()) if source else 0
        doc_density, func_count = _docstring_density(tree)

        return {
            "loc": loc,
            "class_count": _count_classes(tree),
            "max_nesting_depth": _max_nesting_depth(tree),
            "fanout_modules": _fanout_modules(tree),
            "fanout_symbols": _fanout_symbols(tree),
            "comment_density": round(_comment_density(source, loc), 4),
            "docstring_density": round(doc_density, 4),
            "function_count": func_count,
        }

    # ---------------------------------------------------------------
    # Data warnings
    # ---------------------------------------------------------------

    def _compute_data_warnings(self, record: dict) -> list[str]:
        """Apply heuristic checks for suspicious data patterns."""
        warnings: list[str] = []
        loc = record.get("loc")
        if loc is None or loc <= 20:
            return warnings

        # suspect:radon — cc=0 and func_count=0 on non-trivial file
        cc = record.get("cyclomatic_complexity")
        fc = record.get("function_count")
        if cc is not None and fc is not None and cc == 0 and fc == 0:
            warnings.append("suspect:radon")

        # suspect:pylint — score=0.0 when pylint was run
        if self.run_pylint:
            ps = record.get("pylint_score")
            if ps is not None and ps == 0.0:
                warnings.append("suspect:pylint")

        # suspect:mypy — errors=0 and pylint<3.0
        mypy_e = record.get("mypy_errors")
        pylint_s = record.get("pylint_score")
        if (
            mypy_e is not None
            and pylint_s is not None
            and mypy_e == 0
            and pylint_s < 3.0
        ):
            warnings.append("suspect:mypy")

        # suspect:mypy_env — errors/loc > 0.3
        if mypy_e is not None and mypy_e / loc > 0.3:
            warnings.append("suspect:mypy_env")

        return warnings

    # ---------------------------------------------------------------
    # Main annotation method
    # ---------------------------------------------------------------

    def annotate_file(self, path: str, source: str = "", license: str = "") -> dict:
        """Annotate a single Python file.

        Args:
            path: Path to the Python file.
            source: Dataset source name (e.g. "BugsInPy").
            license: License identifier (e.g. "MIT").

        Returns:
            Dict with all Tier 1 fields (and Tier 2 if --full).
        """
        # Try to read the file
        try:
            src = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            return self._null_record(
                path=path,
                source=source,
                license_=license,
                content_sha256=None,
                error_type="io_error",
                error_detail=str(e),
            )

        # Compute content_sha256 (always, even for syntax errors)
        normalized = _normalize_source(src)
        content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        # Try to parse AST (syntax check)
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            return self._null_record(
                path=path,
                source=source,
                license_=license,
                content_sha256=content_sha256,
                error_type="syntax_error",
                error_detail=str(e),
            )

        # --- Layer 1: Tool subprocesses ---
        tool_errors: dict[str, str] = {}

        ruff_violations, ruff_err = self._run_ruff(path)
        if ruff_err:
            tool_errors["ruff"] = ruff_err

        max_cc, func_count_cc, radon_err = self._run_radon_cc_subprocess(path)
        if radon_err:
            tool_errors["radon"] = radon_err

        bandit_high, bandit_medium, bandit_err = self._run_bandit(path)
        if bandit_err:
            tool_errors["bandit"] = bandit_err

        mypy_errors, mypy_err = self._run_mypy(path)
        if mypy_err:
            tool_errors["mypy"] = mypy_err

        pylint_score: Optional[float] = None
        if self.run_pylint:
            pylint_score, pylint_err = self._run_pylint(path)
            if pylint_err:
                tool_errors["pylint"] = pylint_err
        # else: pylint_score stays None

        # --- Layer 2: In-process analysis ---
        radon_metrics = self._layer2_radon(src)
        cognitive_complexity = self._layer2_complexipy(path)
        ast_metrics = self._layer2_ast(src, tree)

        # Use function_count from AST (more authoritative) if radon succeeded,
        # otherwise fall back to radon's count
        function_count = ast_metrics["function_count"]

        # --- Scoring ---
        # For scoring, use 0 for any None tool values
        score = _calculate_score(
            ruff_violations=ruff_violations or 0,
            cyclomatic_complexity=max_cc or 0,
            bandit_high=bandit_high or 0,
            bandit_medium=bandit_medium or 0,
            mypy_errors=mypy_errors or 0,
        )
        grade = _get_grade(score)

        # --- Build record ---
        record: dict = {
            "schema_version": SCHEMA_VERSION,
            "annotator_version": ANNOTATOR_VERSION,
            "tool_versions": dict(self.tool_versions),
            "analysis_config": self._analysis_config(),
            "runtime_env": self._runtime_env(),
            "path": path,
            "content_sha256": content_sha256,
            "source": source,
            "license": license,
            "score": score,
            "grade": grade,
            "ruff_violations": ruff_violations,
            "bandit_high": bandit_high,
            "bandit_medium": bandit_medium,
            "mypy_errors": mypy_errors,
            "pylint_score": pylint_score,
            "loc": ast_metrics["loc"],
            "function_count": function_count,
            "class_count": ast_metrics["class_count"],
            "cyclomatic_complexity": max_cc,
            "avg_complexity": radon_metrics["avg_complexity"],
            "cognitive_complexity": cognitive_complexity,
            "max_nesting_depth": ast_metrics["max_nesting_depth"],
            "n1": radon_metrics["n1"],
            "n2": radon_metrics["n2"],
            "N1": radon_metrics["N1"],
            "N2": radon_metrics["N2"],
            "halstead_volume": radon_metrics["halstead_volume"],
            "halstead_difficulty": radon_metrics["halstead_difficulty"],
            "halstead_effort": radon_metrics["halstead_effort"],
            "maintainability_index": radon_metrics["maintainability_index"],
            "fanout_modules": ast_metrics["fanout_modules"],
            "fanout_symbols": ast_metrics["fanout_symbols"],
            "comment_density": ast_metrics["comment_density"],
            "docstring_density": ast_metrics["docstring_density"],
            "data_warnings": [],
            "tool_errors": tool_errors if tool_errors else None,
            "error_type": None,
            "error_detail": None,
        }

        # Apply data_warnings heuristics
        record["data_warnings"] = self._compute_data_warnings(record)

        # Quality profile (multi-dimensional rating)
        qp = profile_file(record)
        record.update(qp.to_flat_dict())

        # Tier 2 fields (--full only)
        if self.full:
            record.update(self._tier2_fields(src, tree))

        return record

    def _tier2_fields(self, source: str, tree: ast.AST) -> dict:
        """Compute Tier 2 fields (LCOM, CBO). Requires lcom package."""
        import logging

        result: dict = {
            "lcom4_approx": None,
            "lcom5_hs": None,
            "lcom_impl_version": None,
            # CBO fields require inter-file call graph resolution;
            # static approximation is deferred to a future implementation.
            "cbo_approx_static": None,
            "resolved_external_calls": None,
            "unresolved_dynamic_calls": None,
            "cbo_resolution_rate": None,
        }
        try:
            import lcom

            result["lcom_impl_version"] = f"lcom-{lcom.__version__}"

            # Compute LCOM4 and LCOM5 for each class in the module
            lcom4_values: list[int] = []
            lcom5_values: list[float] = []

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # Extract class source lines for lcom analysis
                try:
                    class_source = ast.get_source_segment(source, node)
                    if not class_source:
                        continue
                    # lcom.lcom4 expects the class source string
                    lcom4_val = lcom.lcom4(class_source)
                    lcom4_values.append(lcom4_val)
                except Exception:
                    pass
                try:
                    class_source = ast.get_source_segment(source, node)
                    if not class_source:
                        continue
                    lcom5_val = lcom.lcom5(class_source)
                    lcom5_values.append(lcom5_val)
                except Exception:
                    pass

            if lcom4_values:
                result["lcom4_approx"] = max(lcom4_values)
            if lcom5_values:
                result["lcom5_hs"] = round(sum(lcom5_values) / len(lcom5_values), 4)

        except ImportError:
            if self.full:
                logging.warning(
                    "lcom package not available; lcom4_approx and lcom5_hs "
                    "will be null. Install with: pip install lcom"
                )
        return result

    # ---------------------------------------------------------------
    # Directory and manifest iteration
    # ---------------------------------------------------------------

    def _worker_kwargs(self) -> dict:
        """Return kwargs dict for reconstructing this annotator in a worker process."""
        return {
            "venv_python": self.venv_python,
            "run_pylint": self.run_pylint,
            "full": self.full,
            "workers": 1,  # workers=1 in subprocess to avoid nested pools
            "tool_timeout": self.tool_timeout,
            "isolated": self.isolated,
        }

    def _iter_tasks_parallel(self, tasks: list[tuple[str, str, str]]) -> Iterator[dict]:
        """Process a list of (path, source, license) tasks in parallel.

        Preserves output order using executor.map.

        Args:
            tasks: List of (path, source_name, license_str) tuples.

        Yields:
            Annotation dicts in input order.
        """
        kwargs = self._worker_kwargs()
        args_list = [(kwargs, path, src, lic) for path, src, lic in tasks]
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            for result in executor.map(_annotate_file_worker, args_list):
                yield result

    def annotate_directory(
        self, path: str, exclude: Optional[list[str]] = None
    ) -> Iterator[dict]:
        """Annotate all .py files in a directory tree.

        Args:
            path: Root directory path.
            exclude: Directory names to exclude.

        Yields:
            Annotation dicts, one per .py file.
        """
        exclude_set = set(exclude) if exclude else set()
        root = Path(path)
        py_files = []
        for py_file in sorted(root.rglob("*.py")):
            # Check if any parent directory is in exclude set
            rel_parts = py_file.relative_to(root).parts[:-1]
            if any(part in exclude_set for part in rel_parts):
                continue
            py_files.append(str(py_file))

        if self.workers > 1:
            tasks = [(fp, "", "") for fp in py_files]
            yield from self._iter_tasks_parallel(tasks)
        else:
            for fp in py_files:
                yield self.annotate_file(fp)

    def annotate_manifest(self, manifest_path: str) -> Iterator[dict]:
        """Annotate files listed in a JSONL manifest.

        Each manifest line: {"path": "...", "source": "...", "license": "..."}
        Paths are resolved relative to the manifest's directory if not absolute.

        Yields:
            Annotation dicts.
        """
        manifest = Path(manifest_path)
        manifest_dir = manifest.parent

        entries: list[tuple[str, str, str]] = []
        with manifest.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                file_path = entry["path"]
                if not Path(file_path).is_absolute():
                    file_path = str(manifest_dir / file_path)
                entries.append(
                    (file_path, entry.get("source", ""), entry.get("license", ""))
                )

        if self.workers > 1:
            yield from self._iter_tasks_parallel(entries)
        else:
            for file_path, source, license_str in entries:
                yield self.annotate_file(file_path, source=source, license=license_str)


# ===================================================================
# CLI
# ===================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Annotate Python code files for dataset curation."
    )
    parser.add_argument(
        "input",
        help="Directory of .py files or JSONL manifest",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--source",
        default="",
        help="Dataset source name (for directory mode)",
    )
    parser.add_argument(
        "--license",
        default="",
        help="License identifier (for directory mode)",
    )
    parser.add_argument(
        "--no-pylint",
        action="store_true",
        help="Skip pylint (faster; pylint_score emitted as null)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include Tier 2 fields (LCOM, CBO)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit to first N files",
    )
    parser.add_argument(
        "--tool-timeout",
        type=int,
        default=30,
        help="Per-tool subprocess timeout in seconds",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="*",
        default=[],
        help="Directory names to exclude",
    )

    args = parser.parse_args()

    annotator = DatasetAnnotator(
        run_pylint=not args.no_pylint,
        full=args.full,
        workers=args.workers,
        tool_timeout=args.tool_timeout,
    )

    input_path = Path(args.input)
    if input_path.suffix == ".jsonl":
        records = annotator.annotate_manifest(str(input_path))
    else:
        records = annotator.annotate_directory(str(input_path), exclude=args.exclude)

    count = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for record in records:
            if not args.source == "" and "source" in record:
                record["source"] = record.get("source") or args.source
            if not args.license == "" and "license" in record:
                record["license"] = record.get("license") or args.license
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if args.limit and count >= args.limit:
                break

    print(f"Annotated {count} files -> {args.output}")
