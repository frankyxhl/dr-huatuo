"""Unified CLI entry point for huatuo code quality analysis.

Subcommands:
  check   Analyze file(s) and show quality profile
  report  Generate project report (delegates to code_reporter.py)
  version Show huatuo and tool versions
"""

import argparse
import importlib.metadata
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Optional

from rich.console import Console

from dr_huatuo import __version__
from dr_huatuo.analyzers import ANALYZERS, ToolNotFoundError, create_analyzer
from dr_huatuo.quality_profile import QualityProfile, profile_file

# Grade ordering for quality gate comparisons (higher = worse)
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}

# Security rating ordering (higher = worse)
_SECURITY_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}

console = Console()


# ===================================================================
# File discovery
# ===================================================================


def _supported_extensions() -> set[str]:
    """Return set of file extensions supported by registered analyzers."""
    return set(ANALYZERS.keys())


def _discover_files(
    path: str, exclude: list[str], language: str | None = None
) -> Iterator[Path]:
    """Discover files to analyze based on registered analyzer extensions.

    Args:
        path: File or directory path.
        exclude: Directory names to exclude.
        language: If set, only yield files for this language
            (e.g., "python", "typescript").

    Yields:
        Path objects for each supported file found.

    Raises:
        FileNotFoundError: If path does not exist.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p}")

    if language:
        # Filter extensions to those matching the requested language
        exts = {ext for ext, cls in ANALYZERS.items() if cls.name == language}
    else:
        exts = _supported_extensions()

    if p.is_file():
        if p.suffix in exts:
            yield p
        return

    for f in sorted(p.rglob("*")):
        if f.suffix not in exts:
            continue
        if any(ex in f.parts for ex in exclude):
            continue
        if f.is_file():
            yield f


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

    if profile.type_errors is not None and profile.type_errors > 0:
        console.print(f"  {'Type Safety':<18} {profile.type_errors} errors (info)")

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
            console.print(f"  {short_fn:<25} {dim_name}: [red]D[/red]{detail}")


# ===================================================================
# Subcommands
# ===================================================================


def cmd_check(args: argparse.Namespace) -> int:
    """Run check subcommand: analyze files and show quality profiles.

    Returns exit code: 0 for pass, 1 for quality gate violation.
    """
    default_exclude = [".venv", "__pycache__", ".git", "node_modules"]
    exclude = getattr(args, "exclude", default_exclude)
    language = getattr(args, "language", None)

    try:
        files = list(_discover_files(args.path, exclude, language=language))
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}", highlight=False)
        return 1

    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return 0

    # Group files by analyzer class (not extension) to batch correctly
    by_analyzer: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        cls = ANALYZERS.get(f.suffix)
        if cls:
            by_analyzer[cls.name].append(f)

    profiles: list[tuple[str, QualityProfile]] = []
    skipped_languages: list[str] = []

    # Create one analyzer per language, batch analyze
    for _lang_name, lang_files in by_analyzer.items():
        try:
            project_root = Path(args.path).resolve()
            if project_root.is_file():
                project_root = project_root.parent
            analyzer = create_analyzer(lang_files[0], project_root=project_root)
        except ToolNotFoundError as e:
            console.print(f"[yellow]Skipping {_lang_name} files:[/yellow] {e}")
            skipped_languages.append(_lang_name)
            continue

        if analyzer is None:
            continue

        try:
            batch_results = analyzer.analyze_batch(lang_files)
            for fpath, merged in zip(lang_files, batch_results):
                profile = profile_file(merged)
                profiles.append((str(fpath), profile))
                _render_file_profile(str(fpath), profile)
        except Exception as e:
            console.print(f"\n[red]Error analyzing {_lang_name} files:[/red] {e}")

    if not profiles:
        if skipped_languages:
            # Files found but all analyzers failed — report as error
            console.print("[red]No files could be analyzed (missing tools).[/red]")
            return 1
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
            f"--fail-on {fail_on}" + (f" --dimension {dimension}" if dimension else "")
        )
        return 1

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Run report subcommand: delegate to code_reporter.py."""
    from dr_huatuo.code_reporter import generate_report

    try:
        default_exclude = [".venv", "__pycache__", ".git", "node_modules"]
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
    try:
        version = importlib.metadata.version("dr-huatuo")
    except importlib.metadata.PackageNotFoundError:
        version = __version__
    console.print(f"huatuo {version}")

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
        description="Huatuo (ht) — code quality diagnosis toolkit for Python.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
commands:
  check    5-dimension quality profile (Maintainability, Complexity,
           Code Style, Documentation, Security)
  report   Full project report with per-file breakdown
  version  Show huatuo and tool versions

examples:
  ht check src/app.py           Analyze a single file
  ht check src/                 Analyze all .py files in a directory
  ht check . -e .venv tests     Analyze project, exclude dirs
  ht check src/ --fail-on D     CI gate: fail if any file grades D or F
  ht report src/ -f html -o report.html
                                Generate interactive HTML report
  ht version                    Show installed tool versions

quality dimensions:
  Maintainability   MI (Maintainability Index), 0-100
  Complexity        Cognitive complexity + max nesting depth
  Code Style        Lint violations (ruff) + linter score (pylint)
  Documentation     Docstring coverage + comment density
  Security          Bandit findings (HIGH = FAIL, MEDIUM = WARN)

grades: A (90+) B (80+) C (70+) D (60+) F (<60)

install: pip install dr-huatuo
docs:    https://github.com/frankyxhl/dr-huatuo
""",
    )
    subparsers = parser.add_subparsers(dest="command")

    # check subcommand
    check_parser = subparsers.add_parser(
        "check",
        help="Analyze file(s) and show quality profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  ht check src/app.py                  Single file analysis
  ht check src/                        All .py files in directory
  ht check . -e .venv tests docs       Exclude multiple directories
  ht check src/ --fail-on D            CI: exit 1 if any file is D or F
  ht check src/ --fail-on C            CI: exit 1 if any file is C, D, or F
  ht check src/ --fail-on WARN         CI: exit 1 if any security warning
  ht check src/ --fail-on FAIL         CI: exit 1 only on security FAIL
  ht check src/ --fail-on D --dimension Security
                                       CI: gate on Security dimension only

output:
  Per-file quality profile with 5 dimensions (A-F grades), followed by
  a project summary when analyzing directories. Security dimension uses
  PASS/WARN/FAIL instead of letter grades.
""",
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
        default=[".venv", "__pycache__", ".git", "node_modules"],
        help="Directories to exclude (default: .venv __pycache__ .git node_modules)",
    )
    _lang_choices = sorted({cls.name for cls in ANALYZERS.values()})
    check_parser.add_argument(
        "--language",
        default=None,
        choices=_lang_choices,
        help="Filter by language (e.g., python, typescript)",
    )

    # report subcommand
    report_parser = subparsers.add_parser(
        "report",
        help="Generate project report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  ht report src/                           Terminal report (default)
  ht report src/ -f html -o report.html    Interactive HTML with charts
  ht report src/ -f json -o report.json    Machine-readable JSON
  ht report src/ -f markdown -o report.md  Markdown for documentation
  ht report . -e .venv tests -f html -o out.html
                                           Full project, exclude dirs

formats:
  terminal   Rich-formatted table in terminal (default)
  html       Interactive report with Chart.js, complexity drilldown,
             and source code view
  json       Structured data for CI/CD pipelines and downstream tools
  markdown   Text report suitable for commit messages or docs
""",
    )
    report_parser.add_argument("path", help="Project path")
    report_parser.add_argument(
        "-f",
        "--format",
        choices=["terminal", "json", "markdown", "html"],
        default="terminal",
        help="Output format (default: terminal)",
    )
    report_parser.add_argument("-o", "--output", help="Output file path")
    report_parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[".venv", "__pycache__", ".git", "node_modules"],
        help="Directories to exclude (default: .venv __pycache__ .git node_modules)",
    )

    # version subcommand
    subparsers.add_parser(
        "version",
        help="Show version info",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
example:
  ht version    Shows huatuo version and status of all analysis tools
                (ruff, radon, bandit, mypy, pylint, complexipy)
""",
    )

    return parser


def main() -> None:
    """Main entry point (called by console_scripts)."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "report":
        sys.exit(cmd_report(args))
    elif args.command == "version":
        sys.exit(cmd_version(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
