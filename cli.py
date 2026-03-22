"""Unified CLI entry point for huatuo code quality analysis.

Subcommands:
  check   Analyze file(s) and show quality profile
  report  Generate project report (delegates to code_reporter.py)
  version Show huatuo and tool versions
"""

import argparse
import ast
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Optional

from rich.console import Console

from code_analyzer import CodeAnalyzer, CodeMetrics
from quality_profile import QualityProfile, profile_file

__version__ = "0.2.0"

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

# Grade ordering for quality gate comparisons (higher = worse)
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}

# Security rating ordering (higher = worse)
_SECURITY_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

console = Console()


# ===================================================================
# File discovery
# ===================================================================


def _discover_files(
    path: str, exclude: list[str]
) -> Iterator[Path]:
    """Discover Python files to analyze.

    Args:
        path: File or directory path.
        exclude: Directory names to exclude.

    Yields:
        Path objects for each .py file found.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")

    if p.is_file():
        yield p
        return

    for f in sorted(p.rglob("*.py")):
        # Skip excluded directories
        if any(ex in f.parts for ex in exclude):
            continue
        yield f


# ===================================================================
# Layer 2 metrics gathering
# ===================================================================


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


def _gather_layer2(path: str) -> dict:
    """Compute Layer 2 metrics that CodeMetrics does not provide.

    Returns dict with: maintainability_index, cognitive_complexity,
    max_nesting_depth, docstring_density, comment_density, loc,
    function_count, class_count, data_warnings.
    """
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
    result["comment_density"] = round(_comment_density(source, result["loc"]), 4)

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


# ===================================================================
# Metrics dict construction
# ===================================================================


def _build_metrics_dict(cm: CodeMetrics, layer2: dict) -> dict:
    """Combine CodeMetrics + Layer 2 into a dict for quality_profile.

    Field mapping:
      - cm.max_cyclomatic_complexity -> cyclomatic_complexity
      - cm.functions_analyzed -> (not used, layer2.function_count preferred)
    """
    return {
        "cyclomatic_complexity": cm.max_cyclomatic_complexity,
        "ruff_violations": cm.ruff_violations,
        "pylint_score": cm.pylint_score,
        "mypy_errors": cm.mypy_errors,
        "bandit_high": cm.bandit_high,
        "bandit_medium": cm.bandit_medium,
        "maintainability_index": layer2["maintainability_index"],
        "cognitive_complexity": layer2["cognitive_complexity"],
        "max_nesting_depth": layer2["max_nesting_depth"],
        "docstring_density": layer2["docstring_density"],
        "comment_density": layer2["comment_density"],
        "loc": layer2["loc"],
        "function_count": layer2["function_count"],
        "class_count": layer2["class_count"],
        "data_warnings": layer2["data_warnings"],
    }


# ===================================================================
# Quality gate
# ===================================================================


def _check_quality_gate(
    profiles: list[tuple[str, QualityProfile]],
    fail_on: Optional[str],
    dimension: Optional[str],
) -> bool:
    """Check if any file violates the quality gate.

    Args:
        profiles: List of (filename, QualityProfile) tuples.
        fail_on: Grade threshold (D/C/B) or security threshold (FAIL/WARN), or None.
        dimension: If set, narrow check to this single dimension name.

    Returns:
        True if gate is violated (should exit non-zero).
    """
    if fail_on is None:
        return False

    fail_on_upper = fail_on.upper()

    for _filename, profile in profiles:
        # Grade dimensions (A/B/C/D)
        grade_dims = [
            profile.maintainability,
            profile.complexity,
            profile.code_style,
            profile.documentation,
        ]

        # Security dimension
        sec_dim = profile.security

        # Filter by dimension if specified
        if dimension is not None:
            dim_lower = dimension.lower()
            if dim_lower == "security":
                grade_dims = []
            else:
                grade_dims = [d for d in grade_dims if d.name == dim_lower]
                sec_dim = None  # type: ignore[assignment]

        # Handle security-only gates (FAIL/WARN)
        if fail_on_upper in ("FAIL", "WARN"):
            if sec_dim is not None and sec_dim.rating is not None:
                sec_rank = _SECURITY_ORDER.get(sec_dim.rating, -1)
                threshold_rank = _SECURITY_ORDER.get(fail_on_upper, -1)
                if sec_rank >= threshold_rank:
                    return True
            continue

        # Handle grade gates (D/C/B)
        if fail_on_upper in _GRADE_ORDER:
            threshold = _GRADE_ORDER[fail_on_upper]

            for dim in grade_dims:
                if dim.rating is None:
                    continue
                if dim.rating in _GRADE_ORDER:
                    if _GRADE_ORDER[dim.rating] >= threshold:
                        return True

            # Security interaction: --fail-on D includes FAIL,
            # --fail-on C includes FAIL+WARN
            if sec_dim is not None and sec_dim.rating is not None:
                if fail_on_upper == "D" and sec_dim.rating == "FAIL":
                    return True
                if fail_on_upper == "C" and sec_dim.rating in ("FAIL", "WARN"):
                    return True
                if fail_on_upper == "B" and sec_dim.rating in (
                    "FAIL",
                    "WARN",
                ):
                    return True

    return False


# ===================================================================
# Rendering
# ===================================================================


_GRADE_COLORS = {
    "A": "green",
    "B": "blue",
    "C": "yellow",
    "D": "red",
    "PASS": "green",
    "WARN": "yellow",
    "FAIL": "red",
}

# Action item templates for C/D ratings
_ACTION_ITEMS = {
    "maintainability": {
        "D": "Improve maintainability index (MI < 10 is D, target >= 20 for B)",
        "C": "Improve maintainability index (MI < 20 is C, target >= 40 for A)",
    },
    "complexity": {
        "D": "Reduce cognitive complexity (> 25 is D, target <= 15 for B)",
        "C": "Reduce cognitive complexity (> 15 is C, target <= 5 for A)",
    },
    "code_style": {
        "D": "Fix lint violations (> 10 ruff violations is D, target 0 for A)",
        "C": "Fix lint violations (> 3 ruff violations is C, target 0 for A)",
    },
    "documentation": {
        "D": "Add docstrings (density < 0.20 is D, target >= 0.50 for B)",
        "C": "Add docstrings (density < 0.50 is C, target >= 0.80 for A)",
    },
}


def _render_file_profile(filename: str, profile: QualityProfile) -> None:
    """Render a single file's quality profile to terminal."""
    console.print(f"\n[bold]{filename}[/bold]")

    dims = [
        ("Maintainability", profile.maintainability),
        ("Complexity", profile.complexity),
        ("Code Style", profile.code_style),
        ("Documentation", profile.documentation),
        ("Security", profile.security),
    ]

    for label, dim in dims:
        if dim.rating is None:
            console.print(f"  {label:<18} N/A")
            continue
        color = _GRADE_COLORS.get(dim.rating, "white")
        detail_parts = []
        for k, v in dim.detail.items():
            detail_parts.append(f"{k}={v}")
        detail_str = f"  ({', '.join(detail_parts)})" if detail_parts else ""
        console.print(f"  {label:<18} [{color}]{dim.rating}[/{color}]{detail_str}")

    if profile.mypy_errors is not None and profile.mypy_errors > 0:
        console.print(f"  {'Type Safety':<18} {profile.mypy_errors} errors (info)")

    # Action items for C/D dimensions
    actions = []
    for dim_name, dim in [
        ("maintainability", profile.maintainability),
        ("complexity", profile.complexity),
        ("code_style", profile.code_style),
        ("documentation", profile.documentation),
    ]:
        if dim.rating in ("C", "D") and dim_name in _ACTION_ITEMS:
            msg = _ACTION_ITEMS[dim_name].get(dim.rating)
            if msg:
                actions.append(msg)
    if profile.security.rating == "FAIL":
        actions.append("Fix HIGH severity security issues (bandit)")

    if actions:
        console.print("\n  [bold]Action items:[/bold]")
        for i, action in enumerate(actions, 1):
            console.print(f"    {i}. {action}")


def _render_project_summary(
    profiles: list[tuple[str, QualityProfile]],
) -> None:
    """Render project-level quality summary."""
    console.print(f"\n[bold]Analyzed {len(profiles)} files[/bold]\n")

    dim_names = [
        ("Maintainability", "maintainability"),
        ("Complexity", "complexity"),
        ("Code Style", "code_style"),
        ("Documentation", "documentation"),
        ("Security", "security"),
    ]

    console.print("[bold]Project Quality Summary:[/bold]")
    for label, attr_name in dim_names:
        counts: dict[str, int] = {}
        for _fn, profile in profiles:
            dim = getattr(profile, attr_name)
            if dim.rating is not None:
                counts[dim.rating] = counts.get(dim.rating, 0) + 1

        if attr_name == "security":
            parts = []
            for rating in ("PASS", "WARN", "FAIL"):
                if rating in counts:
                    parts.append(f"{counts[rating]} {rating}")
            console.print(f"  {label:<18} {' '.join(parts)}")
        else:
            parts = []
            for rating in ("A", "B", "C", "D"):
                if rating in counts:
                    color = _GRADE_COLORS[rating]
                    parts.append(f"[{color}]{counts[rating]}{rating}[/{color}]")
            console.print(f"  {label:<18} {' '.join(parts)}")

    # Files with D-rated dimensions
    d_files = []
    for fn, profile in profiles:
        for dim_name, attr_name in [
            ("Maintainability", "maintainability"),
            ("Complexity", "complexity"),
            ("Code Style", "code_style"),
            ("Documentation", "documentation"),
        ]:
            dim = getattr(profile, attr_name)
            if dim.rating == "D":
                detail = ""
                if dim.limiting_metric and dim.detail:
                    detail = f" ({dim.limiting_metric})"
                d_files.append((fn, dim_name, detail))
        if profile.security.rating == "FAIL":
            d_files.append((fn, "Security", " (FAIL)"))

    if d_files:
        console.print("\n[bold]Files with issues (D-rated dimensions):[/bold]")
        for fn, dim_name, detail in d_files:
            short_fn = Path(fn).name
            console.print(
                f"  {short_fn:<25} {dim_name}: [red]D[/red]{detail}"
            )


# ===================================================================
# Subcommands
# ===================================================================


def cmd_check(args: argparse.Namespace) -> int:
    """Run check subcommand: analyze files and show quality profiles.

    Returns exit code: 0 for pass, 1 for quality gate violation.
    """
    default_exclude = [".venv", "__pycache__", ".git"]
    exclude = getattr(args, "exclude", default_exclude)

    try:
        files = list(_discover_files(args.path, exclude))
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}", highlight=False)
        return 1

    if not files:
        console.print("[yellow]No Python files found.[/yellow]")
        return 0

    analyzer = CodeAnalyzer()
    profiles: list[tuple[str, QualityProfile]] = []

    for fpath in files:
        try:
            metrics = analyzer.analyze(str(fpath))
            layer2 = _gather_layer2(str(fpath))
            merged = _build_metrics_dict(metrics, layer2)
            profile = profile_file(merged)
            profiles.append((str(fpath), profile))
            _render_file_profile(str(fpath), profile)
        except Exception as e:
            console.print(f"\n[red]Error analyzing {fpath}:[/red] {e}")

    if not profiles:
        console.print("[yellow]No files could be analyzed.[/yellow]")
        return 0

    # Project summary for directories (more than 1 file)
    if len(profiles) > 1:
        _render_project_summary(profiles)

    # Quality gate
    fail_on = getattr(args, "fail_on", None)
    dimension = getattr(args, "dimension", None)

    if _check_quality_gate(profiles, fail_on, dimension):
        console.print(
            f"\n[red bold]Quality gate failed:[/red bold] "
            f"--fail-on {fail_on}"
            + (f" --dimension {dimension}" if dimension else "")
        )
        return 1

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Run report subcommand: delegate to code_reporter.py."""
    from code_reporter import generate_report

    try:
        default_exclude = [".venv", "__pycache__", ".git"]
        exclude = getattr(args, "exclude", default_exclude)
        output_format = getattr(args, "format", "terminal")
        output_file = getattr(args, "output", None)
        generate_report(args.path, output_format, exclude, output_file)
        return 0
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}", highlight=False)
        return 1


def cmd_version(_args: argparse.Namespace) -> int:
    """Show huatuo version and tool versions."""
    console.print(f"huatuo {__version__}")

    tools = {
        "ruff": ["ruff", "--version"],
        "radon": ["radon", "--version"],
        "bandit": ["bandit", "--version"],
        "mypy": ["mypy", "--version"],
        "pylint": ["pylint", "--version"],
        "complexipy": ["complexipy", "--version"],
    }

    versions = []
    for name, cmd in tools.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            output = (result.stdout + result.stderr).strip()
            # Extract version number from output
            version_str = output.split("\n")[0].strip()
            versions.append(f"{name} {version_str}")
        except Exception:
            versions.append(f"{name} (not found)")

    console.print(f"Tools: {', '.join(versions)}")
    return 0


# ===================================================================
# Argument parsing
# ===================================================================


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="huatuo",
        description="Huatuo code quality analysis toolkit",
    )
    subparsers = parser.add_subparsers(dest="command")

    # check subcommand
    check_parser = subparsers.add_parser(
        "check",
        help="Analyze file(s) and show quality profile",
    )
    check_parser.add_argument("path", help="File or directory to analyze")
    check_parser.add_argument(
        "--fail-on",
        dest="fail_on",
        choices=["D", "C", "B", "FAIL", "WARN"],
        default=None,
        help="Exit non-zero if any file is at or below this grade",
    )
    check_parser.add_argument(
        "--dimension",
        default=None,
        help="Narrow quality gate to a single dimension",
    )
    check_parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[".venv", "__pycache__", ".git"],
        help="Directories to exclude",
    )

    # report subcommand
    report_parser = subparsers.add_parser(
        "report",
        help="Generate project report",
    )
    report_parser.add_argument("path", help="Project path")
    report_parser.add_argument(
        "-f",
        "--format",
        choices=["terminal", "json", "markdown", "html"],
        default="terminal",
        help="Output format",
    )
    report_parser.add_argument("-o", "--output", help="Output file path")
    report_parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[".venv", "__pycache__", ".git"],
        help="Directories to exclude",
    )

    # version subcommand
    subparsers.add_parser("version", help="Show version info")

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "check":
        return cmd_check(args)
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "version":
        return cmd_version(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
