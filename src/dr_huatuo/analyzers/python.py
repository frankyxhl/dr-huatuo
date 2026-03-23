"""Python language analyzer — implements the LanguageAnalyzer protocol."""

import ast
import os
import shutil
import sys
from pathlib import Path
from typing import ClassVar

from dr_huatuo.analyzers.base import BaseAnalyzer, ToolNotFoundError

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


class PythonAnalyzer(BaseAnalyzer):
    """Analyzer for Python files (.py).

    Wraps the existing CodeAnalyzer for Layer 1 (ruff, bandit, mypy, pylint)
    and adds Layer 2 metrics (radon MI, complexipy, AST-based metrics).
    """

    name: ClassVar[str] = "python"
    extensions: ClassVar[list[str]] = [".py"]
    critical_tools: ClassVar[list[str]] = ["ruff", "radon", "bandit", "mypy"]
    optional_tools: ClassVar[list[str]] = ["pylint", "complexipy"]

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root
        self._ensure_venv_on_path()
        self._tool_versions = self.check_tools()
        # Lazy-init: create CodeAnalyzer once for reuse across analyze_file calls
        from dr_huatuo.code_analyzer import CodeAnalyzer

        self._code_analyzer = object.__new__(CodeAnalyzer)
        self._code_analyzer.venv_python = None

    @staticmethod
    def _ensure_venv_on_path() -> None:
        """Add the running Python's bin dir to PATH."""
        bin_dir = str(Path(sys.executable).parent)
        path = os.environ.get("PATH", "")
        if bin_dir not in path.split(os.pathsep):
            os.environ["PATH"] = bin_dir + os.pathsep + path

    def check_tools(self) -> dict[str, str | None]:
        """Check tool availability. Raise for missing critical tools."""
        results: dict[str, str | None] = {}
        missing_critical = []
        missing_optional = []

        for tool in self.critical_tools + self.optional_tools:
            if shutil.which(tool) is not None:
                results[tool] = tool  # version detection deferred
            else:
                results[tool] = None
                if tool in self.critical_tools:
                    missing_critical.append(tool)
                else:
                    missing_optional.append(tool)

        if missing_critical:
            raise ToolNotFoundError(
                f"Critical tools not found: {', '.join(missing_critical)}. "
                f"Run: pip install {' '.join(missing_critical)}"
            )

        if missing_optional:
            print(
                f"Warning: optional tools not installed: {', '.join(missing_optional)}"
            )

        return results

    def analyze_file(self, path: Path) -> dict:
        """Analyze a Python file and return the standard metric dict.

        Combines Layer 1 (CodeAnalyzer subprocess tools) with Layer 2
        (radon MI, complexipy, AST metrics). Emits both legacy and generic
        field names for backward compatibility.
        """
        path = Path(path)

        # --- Layer 1: subprocess tools via CodeAnalyzer ---
        metrics = self._code_analyzer.analyze(str(path))

        # --- Layer 2: radon MI, complexipy, AST metrics ---
        layer2 = self._gather_layer2(str(path))

        # --- Halstead via radon ---
        halstead = self._gather_halstead(str(path))

        # --- Build the full protocol dict ---
        result = {
            # Complexity
            "cyclomatic_complexity": metrics.max_cyclomatic_complexity,
            "avg_complexity": None,
            "cognitive_complexity": layer2["cognitive_complexity"],
            "max_nesting_depth": layer2["max_nesting_depth"],
            # Volume
            "loc": layer2["loc"],
            "function_count": layer2["function_count"],
            "class_count": layer2["class_count"],
            # Readability
            "maintainability_index": layer2["maintainability_index"],
            "comment_density": layer2["comment_density"],
            "docstring_density": layer2["docstring_density"],
            # Code style — generic names
            "lint_violations": metrics.ruff_violations,
            "linter_score": metrics.pylint_score,
            # Security — generic names
            "security_high": metrics.bandit_high,
            "security_medium": metrics.bandit_medium,
            # Type safety — generic name
            "type_errors": metrics.mypy_errors,
            # Halstead
            **halstead,
            # Metadata
            "language": "python",
            "data_warnings": layer2["data_warnings"],
            "error_type": None,
            "error_detail": None,
            "tool_errors": None,
            # Legacy names (dual-emit for backward compat with quality_profile.py)
            "ruff_violations": metrics.ruff_violations,
            "pylint_score": metrics.pylint_score,
            "bandit_high": metrics.bandit_high,
            "bandit_medium": metrics.bandit_medium,
            "mypy_errors": metrics.mypy_errors,
        }

        return result

    # ------------------------------------------------------------------
    # Layer 2 metrics (moved from cli.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _gather_layer2(path: str) -> dict:
        """Compute Layer 2 metrics: MI, cognitive complexity, AST metrics."""
        result: dict = {
            "maintainability_index": None,
            "cognitive_complexity": None,
            "max_nesting_depth": 0,
            "docstring_density": 0.0,
            "comment_density": 0.0,
            "loc": 0,
            "function_count": 0,
            "class_count": 0,
            "data_warnings": [],
        }

        source = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        result["loc"] = len(lines)

        if not source.strip():
            return result

        # AST-based metrics
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return result

        result["max_nesting_depth"] = _max_nesting_depth(tree)
        doc_density, func_count = _docstring_density(tree)
        result["docstring_density"] = round(doc_density, 4)
        result["function_count"] = func_count
        result["class_count"] = _count_classes(tree)
        result["comment_density"] = round(
            _comment_density(source, result["loc"]), 4
        )

        # Maintainability index via radon
        try:
            from radon.metrics import mi_visit

            mi = mi_visit(source, True)
            result["maintainability_index"] = round(mi, 1) if mi is not None else None
        except Exception:
            pass

        # Cognitive complexity via complexipy
        try:
            from complexipy import file_complexity

            fc = file_complexity(path)
            result["cognitive_complexity"] = fc.complexity
        except Exception:
            pass

        return result

    @staticmethod
    def _gather_halstead(path: str) -> dict:
        """Compute Halstead metrics via radon. Returns dict with all fields."""
        halstead = {
            "n1": None,
            "n2": None,
            "N1": None,
            "N2": None,
            "halstead_volume": None,
            "halstead_difficulty": None,
            "halstead_effort": None,
        }
        try:
            from radon.metrics import h_visit

            source = Path(path).read_text(encoding="utf-8", errors="replace")
            results = h_visit(source)
            if results and hasattr(results[0], "volume"):
                h = results[0]
                halstead["n1"] = getattr(h, "h1", None)
                halstead["n2"] = getattr(h, "h2", None)
                halstead["N1"] = getattr(h, "N1", None)
                halstead["N2"] = getattr(h, "N2", None)
                halstead["halstead_volume"] = getattr(h, "volume", None)
                halstead["halstead_difficulty"] = getattr(h, "difficulty", None)
                halstead["halstead_effort"] = getattr(h, "effort", None)
        except Exception:
            pass
        return halstead


# ------------------------------------------------------------------
# AST helper functions (moved from cli.py)
# ------------------------------------------------------------------


def _max_nesting_depth(tree: ast.AST) -> int:
    """Calculate maximum nesting depth of control-flow blocks."""
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
                _walk(child, 0)
            else:
                _walk(child, depth)

    _walk(tree, 0)
    return max_depth


def _docstring_density(tree: ast.AST) -> tuple[float, int]:
    """Calculate docstring_density = functions_with_docstring / function_count."""
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


def _comment_density(source: str, loc: int) -> float:
    """Calculate comment_density = comment_lines / loc."""
    if loc == 0:
        return 0.0
    lines = source.splitlines()
    comment_count = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        if i == 0 and stripped.startswith("#!"):
            continue
        if "coding" in stripped and ("-*-" in stripped or "coding:" in stripped):
            continue
        comment_count += 1
    return comment_count / loc


def _count_classes(tree: ast.AST) -> int:
    """Count all ClassDef nodes."""
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
