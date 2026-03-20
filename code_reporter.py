"""
Python code quality report generator.
Supports multiple output formats: terminal / HTML / Markdown / JSON.
"""

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


@dataclass
class FileMetrics:
    """Metrics for a single file."""

    file_path: str
    max_complexity: int = 0
    avg_complexity: float = 0.0
    func_count: int = 0
    ruff_violations: int = 0
    mypy_errors: int = 0
    bandit_high: int = 0
    bandit_medium: int = 0
    pylint_score: float = 0.0
    line_count: int = 0
    score: float = 0.0
    grade: str = "N/A"

    # Details
    complexity_hotspots: list = field(default_factory=list)
    ruff_issues: list = field(default_factory=list)
    mypy_issues: list = field(default_factory=list)
    bandit_issues: list = field(default_factory=list)


@dataclass
class ProjectReport:
    """Project-level report."""

    project_path: str
    scan_time: str
    total_files: int = 0
    total_lines: int = 0
    total_functions: int = 0

    # Summary metrics
    avg_score: float = 0.0
    avg_complexity: float = 0.0
    max_complexity: int = 0
    total_violations: int = 0
    total_type_errors: int = 0
    total_security_issues: int = 0

    # Grade distribution
    grade_distribution: dict = field(default_factory=dict)

    # File details
    files: list = field(default_factory=list)

    # Hotspots
    complexity_hotspots: list = field(default_factory=list)
    security_hotspots: list = field(default_factory=list)
    type_hotspots: list = field(default_factory=list)


class CodeAnalyzer:
    """Code analysis engine."""

    def __init__(self):
        self._check_tools()

    def _check_tools(self):
        required = ["ruff", "radon", "bandit", "mypy"]
        self.available_tools = {}
        for tool in required:
            result = subprocess.run(["which", tool], capture_output=True)
            self.available_tools[tool] = result.returncode == 0

    def analyze_file(self, file_path: Path) -> FileMetrics:
        """Analyze a single file."""
        metrics = FileMetrics(file_path=str(file_path))

        # Line count
        try:
            content = file_path.read_text()
            metrics.line_count = len(content.splitlines())
        except Exception:
            pass

        # Ruff
        if self.available_tools.get("ruff"):
            ruff_result = self._run_ruff(file_path)
            metrics.ruff_violations = len(ruff_result)
            metrics.ruff_issues = ruff_result[:5]

        # Radon
        if self.available_tools.get("radon"):
            radon_result = self._run_radon(file_path)
            metrics.max_complexity = radon_result.get("max", 0)
            metrics.avg_complexity = radon_result.get("avg", 0)
            metrics.func_count = radon_result.get("count", 0)
            metrics.complexity_hotspots = radon_result.get("hotspots", [])

        # Bandit
        if self.available_tools.get("bandit"):
            bandit_result = self._run_bandit(file_path)
            metrics.bandit_high = sum(
                1 for r in bandit_result if r.get("issue_severity") == "HIGH"
            )
            metrics.bandit_medium = sum(
                1 for r in bandit_result if r.get("issue_severity") == "MEDIUM"
            )
            metrics.bandit_issues = bandit_result[:5]

        # Mypy
        if self.available_tools.get("mypy"):
            mypy_result = self._run_mypy(file_path)
            metrics.mypy_errors = len(mypy_result)
            metrics.mypy_issues = mypy_result[:5]

        # Calculate score
        metrics.score = self._calculate_score(metrics)
        metrics.grade = self._get_grade(metrics.score)

        return metrics

    def analyze_project(
        self, path: str | Path, exclude: Optional[list[str]] = None
    ) -> ProjectReport:
        """Analyze an entire project."""
        resolved = Path(path)
        report = ProjectReport(
            project_path=str(resolved),
            scan_time=datetime.now().isoformat(),
        )

        exclude = exclude or [
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            "node_modules",
            "build",
            "dist",
        ]
        py_files = self._collect_python_files(resolved, exclude)
        report.total_files = len(py_files)

        for py_file in py_files:
            metrics = self.analyze_file(py_file)
            report.files.append(metrics)
            report.total_lines += metrics.line_count
            report.total_functions += metrics.func_count

        self._aggregate_report(report)
        return report

    @staticmethod
    def _collect_python_files(path: Path, exclude: list[str]) -> list[Path]:
        """Collect Python files under *path*, excluding directories in *exclude*.

        Returns a sorted list (lexicographic) for deterministic ordering.
        """
        py_files = [
            p for p in path.rglob("*.py") if not any(ex in p.parts for ex in exclude)
        ]
        py_files.sort()
        return py_files

    @staticmethod
    def _aggregate_report(report: ProjectReport) -> None:
        """Compute all summary statistics on *report* in-place."""
        if not report.files:
            return

        n = len(report.files)
        report.avg_score = sum(f.score for f in report.files) / n
        report.avg_complexity = sum(f.avg_complexity for f in report.files) / n
        report.max_complexity = max(f.max_complexity for f in report.files)
        report.total_violations = sum(f.ruff_violations for f in report.files)
        report.total_type_errors = sum(f.mypy_errors for f in report.files)
        report.total_security_issues = sum(
            f.bandit_high + f.bandit_medium for f in report.files
        )

        # Grade distribution (clear first for idempotency)
        report.grade_distribution = {}
        for f in report.files:
            grade = f.grade[0]  # First character
            report.grade_distribution[grade] = (
                report.grade_distribution.get(grade, 0) + 1
            )

        # Collect hotspots
        CodeAnalyzer._collect_hotspots(report)

    @staticmethod
    def _collect_hotspots(report: ProjectReport) -> None:
        """Collect and truncate hotspot lists on *report*."""
        all_complexity = [
            {**spot, "file": f.file_path}
            for f in report.files
            for spot in f.complexity_hotspots
        ]
        all_security = [
            {**issue, "file": f.file_path}
            for f in report.files
            for issue in f.bandit_issues
        ]
        all_type = [
            {**issue, "file": f.file_path}
            for f in report.files
            for issue in f.mypy_issues
        ]

        report.complexity_hotspots = sorted(
            all_complexity,
            key=lambda x: -x.get("complexity", 0),
        )[:10]
        report.security_hotspots = all_security[:10]
        report.type_hotspots = all_type[:10]

    def _run_ruff(self, path: Path) -> list:
        try:
            result = subprocess.run(
                [
                    "ruff",
                    "check",
                    str(path),
                    "--output-format=json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return json.loads(result.stdout) if result.stdout else []
        except Exception:
            return []

    def _run_radon(self, path: Path) -> dict:
        try:
            result = subprocess.run(
                ["radon", "cc", str(path), "-j"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            data = json.loads(result.stdout) if result.stdout else {}
            all_funcs = []
            for file_path, funcs in data.items():
                for f in funcs:
                    f["_file"] = file_path
                    all_funcs.append(f)

            if all_funcs:
                complexities = [f.get("complexity", 0) for f in all_funcs]

                # Detailed complexity analysis
                hotspots = []
                for f in sorted(
                    all_funcs,
                    key=lambda x: -x.get("complexity", 0),
                )[:10]:
                    hotspot = {
                        "name": f["name"],
                        "line": f["lineno"],
                        "complexity": f["complexity"],
                        "file": f.get("_file", ""),
                        "breakdown": (self._analyze_complexity_breakdown(path, f)),
                    }
                    hotspots.append(hotspot)

                return {
                    "max": max(complexities),
                    "avg": (sum(complexities) / len(complexities)),
                    "count": len(all_funcs),
                    "hotspots": hotspots,
                }
        except Exception:
            pass
        return {"max": 0, "avg": 0, "count": 0, "hotspots": []}

    def _analyze_complexity_breakdown(self, path: Path, func_info: dict) -> dict:
        """Analyze function complexity breakdown with branch point details."""
        try:
            import ast

            # Get file content
            file_path = Path(func_info.get("_file", str(path)))
            if not file_path.exists():
                return {"error": "File not found"}

            content = file_path.read_text()
            tree = ast.parse(content)

            # Find target function
            func_name = func_info["name"]
            target_func = None

            for node in ast.walk(tree):
                if (
                    isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == func_name
                ):
                    target_func = node
                    break

            if not target_func:
                return {"error": f"Function {func_name} not found"}

            # Analyze branch points

            class BranchVisitor(ast.NodeVisitor):
                def __init__(self):
                    self.branches = []

                def visit_If(self, node):
                    self.branches.append(
                        {
                            "type": "if",
                            "line": node.lineno,
                            "description": "if statement",
                        }
                    )
                    self.generic_visit(node)

                def visit_For(self, node):
                    self.branches.append(
                        {
                            "type": "for",
                            "line": node.lineno,
                            "description": "for loop",
                        }
                    )
                    self.generic_visit(node)

                def visit_While(self, node):
                    self.branches.append(
                        {
                            "type": "while",
                            "line": node.lineno,
                            "description": "while loop",
                        }
                    )
                    self.generic_visit(node)

                def visit_ExceptHandler(self, node):
                    self.branches.append(
                        {
                            "type": "except",
                            "line": node.lineno,
                            "description": "except handler",
                        }
                    )
                    self.generic_visit(node)

                def visit_BoolOp(self, node):
                    # and/or operator: each extra operand +1
                    op_name = "and" if isinstance(node.op, ast.And) else "or"
                    for _i in range(len(node.values) - 1):
                        self.branches.append(
                            {
                                "type": "and/or",
                                "line": node.lineno,
                                "description": (f"{op_name} logical operation"),
                            }
                        )
                    self.generic_visit(node)

                def visit_IfExp(self, node):
                    self.branches.append(
                        {
                            "type": "ternary",
                            "line": node.lineno,
                            "description": ("ternary expression (x if cond else y)"),
                        }
                    )
                    self.generic_visit(node)

                def visit_comprehension(self, node):
                    self.branches.append(
                        {
                            "type": "comprehension",
                            "line": node.lineno,
                            "description": ("list/dict/set comprehension"),
                        }
                    )
                    self.generic_visit(node)

            visitor = BranchVisitor()
            visitor.visit(target_func)

            # Type-count statistics
            from collections import Counter

            type_count = Counter(b["type"] for b in visitor.branches)

            # Calculate complexity
            # Base complexity = 1
            # Each branch point +1
            calculated = 1 + len(visitor.branches)

            # Get function source snippet
            lines = content.split("\n")
            start_line = target_func.lineno
            end_line = target_func.end_lineno or start_line + 20
            code_snippet = "\n".join(
                lines[start_line - 1 : min(end_line, start_line + 30)]
            )

            return {
                "base_complexity": 1,
                "branches": visitor.branches[:30],  # Limit returned count
                "branch_count": len(visitor.branches),
                "type_breakdown": dict(type_count),
                "calculated_complexity": calculated,
                "radon_complexity": func_info["complexity"],
                "start_line": start_line,
                "end_line": end_line,
                "code_snippet": code_snippet,
            }
        except Exception as e:
            return {"error": str(e)}

    def _run_bandit(self, path: Path) -> list:
        try:
            result = subprocess.run(
                ["bandit", "-r", str(path), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            data = json.loads(result.stdout) if result.stdout else {}
            return data.get("results", [])
        except Exception:
            return []

    def _run_mypy(self, path: Path) -> list:
        try:
            result = subprocess.run(
                [
                    "mypy",
                    str(path),
                    "--output=json",
                    "--no-error-summary",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            errors = []
            for line in result.stdout.strip().split("\n"):
                if line and line.startswith("{"):
                    try:
                        errors.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return errors
        except Exception:
            return []

    def _calculate_score(self, m: FileMetrics) -> float:
        score = 100.0
        score -= min(m.ruff_violations * 2, 30)
        if m.max_complexity > 10:
            score -= min((m.max_complexity - 10) * 3, 25)
        score -= min(m.bandit_high * 15, 30)
        score -= min(m.bandit_medium * 5, 15)
        score -= min(m.mypy_errors, 10)
        return max(score, 0)

    def _get_grade(self, score: float) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"


class ReportRenderer:
    """Report renderer."""

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()

    def render_terminal(self, report: ProjectReport):
        """Render formatted terminal output."""

        # 1. Title panel
        self._render_header(report)

        # 2. Overview
        self._render_overview(report)

        # 3. Grade distribution
        self._render_grade_distribution(report)

        # 4. Risk hotspots
        self._render_hotspots(report)

        # 5. File details table
        self._render_files_table(report)

        # 6. Suggested actions
        self._render_actions(report)

    def _render_header(self, report: ProjectReport):
        title = Text()
        title.append("Python Code Quality Report", style="bold cyan")

        info = Text()
        info.append(f"{report.project_path}\n", style="dim")
        info.append(f"{report.scan_time}\n", style="dim")
        info.append(
            (
                f"{report.total_files} files"
                f" | {report.total_lines} lines"
                f" | {report.total_functions} functions"
            ),
            style="dim",
        )

        panel = Panel(
            info,
            title=title,
            border_style="cyan",
            box=box.DOUBLE,
        )
        self.console.print(panel)
        self.console.print()

    def _render_overview(self, report: ProjectReport):
        # Score display
        score_color = self._get_score_color(report.avg_score)

        score_text = Text()
        score_text.append(
            f"{report.avg_score:.0f}",
            style=f"bold {score_color}",
        )
        score_text.append("/100", style="dim")

        grade_text = Text()
        grade_text.append(
            f" {self._get_grade_label(report.avg_score)} ",
            style=(f"bold {score_color} on {score_color}20"),
        )

        # Metrics panel
        metrics_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        metrics_table.add_column("metric", style="dim")
        metrics_table.add_column("value", justify="right")

        metrics_table.add_row(
            "Avg Complexity",
            f"{report.avg_complexity:.1f}",
        )
        metrics_table.add_row("Max Complexity", str(report.max_complexity))
        metrics_table.add_row("Violations", str(report.total_violations))
        metrics_table.add_row("Type Errors", str(report.total_type_errors))
        metrics_table.add_row(
            "Security Issues",
            str(report.total_security_issues),
        )

        # Combined display
        self.console.print(
            Columns(
                [
                    Panel(
                        score_text,
                        title="Overall Score",
                        width=20,
                    ),
                    Panel(grade_text, title="Grade", width=20),
                    Panel(
                        metrics_table,
                        title="Key Metrics",
                        width=30,
                    ),
                ]
            )
        )
        self.console.print()

    def _render_grade_distribution(self, report: ProjectReport):
        if not report.grade_distribution:
            return

        table = Table(
            title="Grade Distribution",
            box=box.SIMPLE,
            show_header=True,
        )
        table.add_column("Grade", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Percent", justify="right")
        table.add_column("Distribution", width=20)

        total = sum(report.grade_distribution.values())
        grades = ["A", "B", "C", "D", "F"]

        for grade in grades:
            count = report.grade_distribution.get(grade, 0)
            pct = count / total * 100 if total > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            color = self._get_score_color(self._grade_to_score(grade))

            table.add_row(
                f"[{color}]{grade}[/{color}]",
                str(count),
                f"{pct:.1f}%",
                f"[{color}]{bar}[/{color}]",
            )

        self.console.print(table)
        self.console.print()

    def _render_hotspots(self, report: ProjectReport):
        # Complexity hotspots
        if report.complexity_hotspots:
            table = Table(
                title="Complexity Hotspots (need refactoring)",
                box=box.SIMPLE,
            )
            table.add_column("Complexity", justify="right", width=8)
            table.add_column("Function", width=30)
            table.add_column("Location", width=40)

            for spot in report.complexity_hotspots[:5]:
                cc = spot["complexity"]
                color = "red" if cc > 20 else "yellow" if cc > 10 else "green"
                rel_path = self._relative_path(
                    spot.get("file", ""), report.project_path
                )
                table.add_row(
                    f"[{color}]{cc}[/{color}]",
                    spot["name"],
                    f"{rel_path}:{spot['line']}",
                )

            self.console.print(table)
            self.console.print()

        # Security hotspots
        if report.security_hotspots:
            table = Table(title="Security Issues", box=box.SIMPLE)
            table.add_column("Severity", width=8)
            table.add_column("Issue", width=40)
            table.add_column("Location", width=30)

            for issue in report.security_hotspots[:5]:
                sev = issue.get("issue_severity", "LOW")
                color = "red" if sev == "HIGH" else "yellow"
                rel_path = self._relative_path(
                    issue.get("file", ""),
                    report.project_path,
                )
                table.add_row(
                    f"[{color}]{sev}[/{color}]",
                    issue.get("issue_text", "")[:40],
                    (f"{rel_path}:{issue.get('line_number', '?')}"),
                )

            self.console.print(table)
            self.console.print()

    def _render_files_table(self, report: ProjectReport):
        if not report.files:
            return

        # Sort by score
        sorted_files = sorted(report.files, key=lambda f: f.score)

        table = Table(
            title="File Details (sorted by score)",
            box=box.SIMPLE,
            show_lines=True,
        )
        table.add_column("Score", justify="right", width=8)
        table.add_column("File", width=35)
        table.add_column("Complexity", justify="right", width=8)
        table.add_column("Violations", justify="right", width=6)
        table.add_column("Types", justify="right", width=6)
        table.add_column("Security", justify="right", width=6)
        table.add_column("Lines", justify="right", width=6)

        for f in sorted_files[:15]:  # Show at most 15
            color = self._get_score_color(f.score)
            rel_path = self._relative_path(f.file_path, report.project_path)

            cc_color = (
                "red"
                if f.max_complexity > 20
                else "yellow"
                if f.max_complexity > 10
                else ""
            )
            cc_text = (
                f"[{cc_color}]{f.max_complexity}[/{cc_color}]"
                if cc_color
                else str(f.max_complexity)
            )

            table.add_row(
                f"[{color}]{f.score:.0f}[/{color}]",
                rel_path,
                cc_text,
                (str(f.ruff_violations) if f.ruff_violations else "-"),
                (str(f.mypy_errors) if f.mypy_errors else "-"),
                (
                    str(f.bandit_high + f.bandit_medium)
                    if (f.bandit_high + f.bandit_medium)
                    else "-"
                ),
                str(f.line_count),
            )

        if len(sorted_files) > 15:
            table.add_row(
                "...",
                (f"({len(sorted_files) - 15} more files)"),
                "",
                "",
                "",
                "",
                "",
            )

        self.console.print(table)
        self.console.print()

    def _render_actions(self, report: ProjectReport):
        actions = []

        # Generate suggestions based on analysis results
        if report.max_complexity > 20:
            actions.append(
                (
                    "HIGH",
                    (
                        "Refactor functions with"
                        " complexity > 20 (current max"
                        f" {report.max_complexity})"
                    ),
                )
            )

        if report.total_security_issues > 0:
            actions.append(
                (
                    "HIGH",
                    (f"Fix {report.total_security_issues} security issues"),
                )
            )

        if report.total_type_errors > 5:
            actions.append(
                (
                    "MEDIUM",
                    (f"Fix {report.total_type_errors} type errors"),
                )
            )

        if report.total_violations > 20:
            actions.append(
                (
                    "MEDIUM",
                    (f"Clean up {report.total_violations} code style violations"),
                )
            )

        if report.avg_score < 70:
            actions.append(
                (
                    "MEDIUM",
                    ("Overall code quality is low; consider an improvement plan"),
                )
            )

        if not actions:
            actions.append(("LOW", "Code quality is good; keep it up!"))

        table = Table(
            title="Suggested Actions",
            box=box.SIMPLE,
            show_header=False,
        )
        table.add_column("Priority", width=10)
        table.add_column("Action")

        for priority, action in actions:
            table.add_row(priority, action)

        self.console.print(table)

    def _get_score_color(self, score: float) -> str:
        if score >= 80:
            return "green"
        if score >= 60:
            return "yellow"
        return "red"

    def _get_grade_label(self, score: float) -> str:
        if score >= 90:
            return "A Excellent"
        if score >= 80:
            return "B Good"
        if score >= 70:
            return "C Fair"
        if score >= 60:
            return "D Pass"
        return "F Fail"

    def _grade_to_score(self, grade: str) -> float:
        mapping = {
            "A": 95,
            "B": 85,
            "C": 75,
            "D": 65,
            "F": 50,
        }
        return mapping.get(grade, 0)

    def _relative_path(self, full_path: str, base_path: str) -> str:
        try:
            return str(Path(full_path).relative_to(base_path))
        except ValueError:
            return full_path

    def render_json(self, report: ProjectReport) -> str:
        """JSON output."""
        return json.dumps(
            asdict(report),
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    def render_markdown(self, report: ProjectReport) -> str:
        """Markdown output."""
        lines = [
            "# Python Code Quality Report",
            "",
            f"**Project**: `{report.project_path}`",
            f"**Time**: {report.scan_time}",
            (
                f"**Files**: {report.total_files}"
                f" | **Lines**: {report.total_lines}"
                f" | **Functions**: {report.total_functions}"
            ),
            "",
            "## Overall Score",
            "",
            "| Metric | Value |",
            "|------|-----|",
            (f"| Overall Score | **{report.avg_score:.0f}**/100 |"),
            (f"| Grade | **{self._get_grade_label(report.avg_score)}** |"),
            (f"| Avg Complexity | {report.avg_complexity:.1f} |"),
            (f"| Max Complexity | {report.max_complexity} |"),
            (f"| Violations | {report.total_violations} |"),
            (f"| Type Errors | {report.total_type_errors} |"),
            (f"| Security Issues | {report.total_security_issues} |"),
            "",
            "## Grade Distribution",
            "",
            "| Grade | Count |",
            "|------|------|",
        ]

        for grade in ["A", "B", "C", "D", "F"]:
            count = report.grade_distribution.get(grade, 0)
            lines.append(f"| {grade} | {count} |")

        if report.complexity_hotspots:
            lines.extend(
                [
                    "",
                    "## Complexity Hotspots",
                    "",
                    "| Complexity | Function | Location |",
                    "|--------|------|------|",
                ]
            )
            for spot in report.complexity_hotspots[:10]:
                lines.append(
                    f"| {spot['complexity']}"
                    f" | `{spot['name']}`"
                    f" | `{spot.get('file', '')}"
                    f":{spot['line']}` |"
                )

        lines.extend(
            [
                "",
                "---",
                "*Generated by Code Analyzer*",
            ]
        )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Data-preparation helpers for render_html
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_grade_chart_data(report: ProjectReport) -> dict:
        """Return grade chart data: {labels, values, colors}."""
        labels = ["A", "B", "C", "D", "F"]
        values = [report.grade_distribution.get(g, 0) for g in labels]
        colors = ["#22c55e", "#84cc16", "#eab308", "#f97316", "#ef4444"]
        return {"labels": labels, "values": values, "colors": colors}

    @staticmethod
    def _prepare_complexity_ranges(report: ProjectReport) -> dict:
        """Return complexity distribution counts."""
        ranges: dict[str, int] = {
            "1-5": 0,
            "6-10": 0,
            "11-20": 0,
            "21-50": 0,
            "50+": 0,
        }
        for f in report.files:
            cc = f.max_complexity
            if cc <= 5:
                ranges["1-5"] += 1
            elif cc <= 10:
                ranges["6-10"] += 1
            elif cc <= 20:
                ranges["11-20"] += 1
            elif cc <= 50:
                ranges["21-50"] += 1
            else:
                ranges["50+"] += 1
        return ranges

    @staticmethod
    def _prepare_actions(report: ProjectReport) -> list[dict]:
        """Return suggested action items with priority and text."""
        actions: list[dict] = []
        if report.max_complexity > 20:
            actions.append(
                {
                    "priority": "high",
                    "text": (
                        "Refactor functions with"
                        " complexity > 20 (current max"
                        f" {report.max_complexity})"
                    ),
                }
            )
        if report.total_security_issues > 0:
            actions.append(
                {
                    "priority": "high",
                    "text": f"Fix {report.total_security_issues} security issues",
                }
            )
        if report.total_type_errors > 5:
            actions.append(
                {
                    "priority": "medium",
                    "text": f"Fix {report.total_type_errors} type errors",
                }
            )
        if report.total_violations > 20:
            actions.append(
                {
                    "priority": "medium",
                    "text": (
                        f"Clean up {report.total_violations} code style violations"
                    ),
                }
            )
        if report.avg_score < 70:
            actions.append(
                {
                    "priority": "medium",
                    "text": (
                        "Overall code quality is low; consider an improvement plan"
                    ),
                }
            )
        if not actions:
            actions.append(
                {
                    "priority": "low",
                    "text": "Code quality is good; keep it up!",
                }
            )
        return actions

    def _prepare_files_json(self, report: ProjectReport) -> str:
        """Return JSON string of file detail data for JS template."""
        return json.dumps(
            [
                {
                    "path": self._relative_path(f.file_path, report.project_path),
                    "full_path": f.file_path,
                    "score": f.score,
                    "max_complexity": f.max_complexity,
                    "ruff_violations": f.ruff_violations,
                    "mypy_errors": f.mypy_errors,
                    "bandit_high": f.bandit_high,
                    "bandit_medium": f.bandit_medium,
                    "line_count": f.line_count,
                    "complexity_hotspots": f.complexity_hotspots,
                    "ruff_issues": f.ruff_issues,
                    "mypy_issues": f.mypy_issues,
                    "bandit_issues": f.bandit_issues,
                }
                for f in report.files
            ]
        )

    def render_html(self, report: ProjectReport) -> str:
        """HTML output - full web report with charts, Light/Dark mode."""

        # Prepare data via helper methods
        grade_chart = self._prepare_grade_chart_data(report)
        grade_labels = grade_chart["labels"]
        grade_values = grade_chart["values"]
        grade_colors = grade_chart["colors"]

        complexity_ranges = self._prepare_complexity_ranges(report)
        actions = self._prepare_actions(report)
        files_json = self._prepare_files_json(report)

        score_color = self._get_score_color(report.avg_score)
        grade_label = self._get_grade_label(report.avg_score)

        cc_class = (
            "high"
            if report.max_complexity > 20
            else "medium"
            if report.max_complexity > 10
            else "low"
        )
        sec_class = "high" if report.total_security_issues > 0 else "low"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Python Code Quality Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: rgba(255,255,255,0.05);
            --text-primary: #e2e8f0;
            --text-secondary: #94a3b8;
            --border-color: rgba(255,255,255,0.1);
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
        }}

        [data-theme="light"] {{
            --bg-primary: #f8fafc;
            --bg-secondary: #e2e8f0;
            --bg-card: rgba(0,0,0,0.03);
            --text-primary: #1e293b;
            --text-secondary: #64748b;
            --border-color: rgba(0,0,0,0.1);
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont,
                'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            min-height: 100vh;
            color: var(--text-primary);
            padding: 2rem;
            transition: all 0.3s ease;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}

        /* Theme Toggle */
        .theme-toggle {{
            position: fixed;
            top: 1rem;
            right: 1rem;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 2rem;
            padding: 0.5rem 1rem;
            cursor: pointer;
            color: var(--text-primary);
            font-size: 0.9rem;
            z-index: 1000;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .theme-toggle:hover {{ opacity: 0.8; }}

        /* Header */
        .header {{
            text-align: center;
            margin-bottom: 2rem;
            padding: 2rem;
            background: var(--bg-card);
            border-radius: 1rem;
            border: 1px solid var(--border-color);
        }}
        .header h1 {{
            font-size: 2rem; margin-bottom: 0.5rem;
        }}
        .header .meta {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        /* Score Card */
        .score-section {{
            display: grid;
            grid-template-columns: 200px 1fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }}
        .score-card {{
            background: var(--bg-card);
            border-radius: 1rem;
            padding: 2rem;
            text-align: center;
            border: 2px solid {score_color};
            box-shadow: var(--shadow);
        }}
        .score-value {{
            font-size: 4rem;
            font-weight: bold;
            color: {score_color};
        }}
        .score-label {{
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }}
        .grade-badge {{
            display: inline-block;
            padding: 0.5rem 1.5rem;
            background: {score_color}20;
            color: {score_color};
            border-radius: 2rem;
            font-weight: bold;
            margin-top: 1rem;
        }}

        /* Metrics Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(
                auto-fit, minmax(150px, 1fr)
            );
            gap: 1rem;
        }}
        .metric-card {{
            background: var(--bg-card);
            border-radius: 0.5rem;
            padding: 1rem;
            text-align: center;
            border: 1px solid var(--border-color);
        }}
        .metric-value {{
            font-size: 1.5rem; font-weight: bold;
        }}
        .metric-label {{
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}

        /* Section Card */
        .section-card {{
            background: var(--bg-card);
            border-radius: 1rem;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }}
        .section-card h3 {{
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        /* Charts Section */
        .charts-section {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }}

        /* Hotspots */
        .hotspots-section {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }}

        /* Table */
        table {{
            width: 100%; border-collapse: collapse;
        }}
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            color: var(--text-secondary);
            font-weight: 500;
        }}
        tr:hover {{ background: var(--bg-card); }}
        code {{
            background: rgba(128,128,128,0.2);
            padding: 0.2rem 0.4rem;
            border-radius: 0.25rem;
            font-size: 0.85em;
        }}

        .complexity-high {{
            color: #ef4444; font-weight: bold;
        }}
        .complexity-medium {{ color: #f97316; }}
        .complexity-low {{ color: #22c55e; }}

        /* Actions */
        .action-item {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background: var(--bg-secondary);
            border-radius: 0.5rem;
        }}
        .action-priority {{
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.8rem;
            font-weight: bold;
            white-space: nowrap;
        }}
        .priority-high {{
            background: #ef4444; color: white;
        }}
        .priority-medium {{
            background: #f97316; color: white;
        }}
        .priority-low {{
            background: #22c55e; color: white;
        }}

        /* Files Table */
        .file-row {{
            cursor: pointer;
            transition: all 0.2s;
        }}
        .file-row:hover {{
            background: rgba(100,100,100,0.1);
        }}
        .file-details {{
            display: none;
            background: var(--bg-secondary);
            border-radius: 0.5rem;
            padding: 1rem;
            margin: 0.5rem 0;
            border-left: 3px solid {score_color};
        }}
        .file-details.active {{ display: block; }}
        .file-details h4 {{
            margin-bottom: 0.75rem;
            color: var(--text-secondary);
        }}
        .detail-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }}
        .detail-item {{
            background: var(--bg-card);
            padding: 0.75rem;
            border-radius: 0.5rem;
        }}
        .detail-item h5 {{
            color: var(--text-secondary);
            font-size: 0.8rem;
            margin-bottom: 0.5rem;
        }}
        .detail-item ul {{
            list-style: none;
            font-size: 0.85rem;
        }}
        .detail-item li {{
            padding: 0.25rem 0;
            border-bottom: 1px solid var(--border-color);
        }}
        .detail-item li:last-child {{
            border-bottom: none;
        }}

        /* Expand Icon */
        .expand-icon {{
            display: inline-block;
            transition: transform 0.2s;
        }}
        .file-row.expanded .expand-icon {{
            transform: rotate(90deg);
        }}

        /* Tabs */
        .tabs {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
        }}
        .tab {{
            padding: 0.5rem 1rem;
            cursor: pointer;
            border-radius: 0.5rem 0.5rem 0 0;
            color: var(--text-secondary);
            transition: all 0.2s;
        }}
        .tab:hover {{ background: var(--bg-card); }}
        .tab.active {{
            background: var(--bg-card);
            color: var(--text-primary);
            border-bottom: 2px solid {score_color};
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            .score-section {{
                grid-template-columns: 1fr;
            }}
            .charts-section {{
                grid-template-columns: 1fr;
            }}
            .hotspots-section {{
                grid-template-columns: 1fr;
            }}
            .detail-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <button class="theme-toggle" onclick="toggleTheme()">
        <span id="theme-icon">Dark</span>
    </button>

    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>Python Code Quality Report</h1>
            <div class="meta">
                {report.project_path} |
                {report.scan_time} |
                {report.total_files} files |
                {report.total_lines} lines |
                {report.total_functions} functions
            </div>
        </div>

        <!-- Score Section -->
        <div class="score-section">
            <div class="score-card">
                <div class="score-value">\
{report.avg_score:.0f}</div>
                <div class="score-label">\
Overall Score</div>
                <div class="grade-badge">\
{grade_label}</div>
            </div>
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-value">\
{report.avg_complexity:.1f}</div>
                    <div class="metric-label">\
Avg Complexity</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value \
complexity-{cc_class}">\
{report.max_complexity}</div>
                    <div class="metric-label">\
Max Complexity</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">\
{report.total_violations}</div>
                    <div class="metric-label">\
Violations</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">\
{report.total_type_errors}</div>
                    <div class="metric-label">\
Type Errors</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value \
complexity-{sec_class}">\
{report.total_security_issues}</div>
                    <div class="metric-label">\
Security Issues</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">\
{report.total_files}</div>
                    <div class="metric-label">\
Files</div>
                </div>
            </div>
        </div>

        <!-- Charts -->
        <div class="charts-section">
            <div class="section-card">
                <h3>Grade Distribution</h3>
                <canvas id="gradeChart"></canvas>
            </div>
            <div class="section-card">
                <h3>Complexity Distribution</h3>
                <canvas id="complexityChart"></canvas>
            </div>
        </div>

        <!-- Hotspots -->
        <div class="hotspots-section">
            <div class="section-card">
                <h3>Complexity Hotspots \
<span style="font-size:0.8em; \
color: var(--text-secondary);">\
(click to expand)</span></h3>
                <table>
                    <thead>
                        <tr>
                            <th width="30"></th>
                            <th>Complexity</th>
                            <th>Function</th>
                            <th>Location</th>
                        </tr>
                    </thead>
                    <tbody>
                        \
{self._generate_complexity_rows_with_expand(report)}
                    </tbody>
                </table>
                \
{self._generate_complexity_details_html(report)}
            </div>
            <div class="section-card">
                <h3>Security Issues</h3>
                {self._generate_security_table(report)}
            </div>
        </div>

        <!-- Actions -->
        <div class="section-card">
            <h3>Suggested Actions</h3>
            {self._generate_actions_html(actions)}
        </div>

        <!-- Files Table -->
        <div class="section-card">
            <h3>File Details (click to expand)</h3>
            <div class="tabs">
                <div class="tab active" \
onclick="filterFiles('all')">\
All ({len(report.files)})</div>
                <div class="tab" \
onclick="filterFiles('low')">\
Needs Attention (score&lt;80)</div>
                <div class="tab" \
onclick="filterFiles('complexity')">\
High Complexity (&gt;10)</div>
            </div>
            <table id="files-table">
                <thead>
                    <tr>
                        <th width="30"></th>
                        <th>Score</th>
                        <th>File</th>
                        <th>Complexity</th>
                        <th>Violations</th>
                        <th>Types</th>
                        <th>Security</th>
                        <th>Lines</th>
                    </tr>
                </thead>
                <tbody id="files-body">
                </tbody>
            </table>
        </div>
    </div>

    <!-- File Data -->
    <script id="files-data" \
type="application/json">{files_json}</script>

    <script>
        // Theme Toggle
        function toggleTheme() {{
            const body = document.body;
            const isDark = \
body.getAttribute('data-theme') !== 'light';
            body.setAttribute(\
'data-theme', isDark ? 'light' : 'dark');
            document.getElementById(\
'theme-icon').textContent = \
isDark ? 'Light' : 'Dark';
            updateChartColors();
        }}

        // File Data
        const filesData = JSON.parse(\
document.getElementById(\
'files-data').textContent);

        // Render Files Table
        function renderFiles(filter = 'all') {{
            const tbody = \
document.getElementById('files-body');
            let filtered = filesData;

            if (filter === 'low') {{
                filtered = \
filesData.filter(f => f.score < 80);
            }} else if (filter === 'complexity') {{
                filtered = \
filesData.filter(f => f.max_complexity > 10);
            }}

            // Sort by score
            filtered.sort((a, b) => a.score - b.score);

            let html = '';
            filtered.forEach((f, i) => {{
                const scoreColor = f.score >= 80 \
? '#22c55e' : f.score >= 60 ? '#eab308' : '#ef4444';
                const ccClass = f.max_complexity > 20 \
? 'complexity-high' : f.max_complexity > 10 \
? 'complexity-medium' : '';

                html += '<tr class="file-row" \
onclick="toggleFileDetails(' + i + ')" \
data-score="' + f.score + '" \
data-complexity="' + f.max_complexity + '">';
                html += '<td><span \
class="expand-icon">&#9654;</span></td>';
                html += '<td style="color: ' \
+ scoreColor + '; font-weight: bold;">' \
+ f.score.toFixed(0) + '</td>';
                html += '<td><code>' \
+ f.path + '</code></td>';
                html += '<td class="' \
+ ccClass + '">' + f.max_complexity + '</td>';
                html += '<td>' \
+ (f.ruff_violations || '-') + '</td>';
                html += '<td>' \
+ (f.mypy_errors || '-') + '</td>';
                html += '<td>' \
+ ((f.bandit_high + f.bandit_medium) || '-') + '</td>';
                html += '<td>' \
+ f.line_count + '</td>';
                html += '</tr>';
                html += '<tr><td colspan="8">\
<div class="file-details" \
id="file-details-' + i + '">';
                html += renderFileDetails(f);
                html += '</div></td></tr>';
            }});
            tbody.innerHTML = html;
        }}

        function renderFileDetails(f) {{
            let html = '<div class="detail-grid">';

            // Complexity Hotspots
            if (f.complexity_hotspots \
&& f.complexity_hotspots.length > 0) {{
                html += '<div class="detail-item">\
<h5>Complexity Hotspots</h5><ul>';
                f.complexity_hotspots.forEach(s => {{
                    const ccClass = s.complexity > 20 \
? 'complexity-high' : 'complexity-medium';
                    html += '<li><span class="' \
+ ccClass + '">' + s.complexity \
+ '</span> - ' + s.name \
+ ' (L' + s.line + ')</li>';
                }});
                html += '</ul></div>';
            }}

            // Ruff Issues
            if (f.ruff_issues \
&& f.ruff_issues.length > 0) {{
                html += '<div class="detail-item">\
<h5>Ruff Violations</h5><ul>';
                f.ruff_issues.slice(0, 5).forEach(r => {{
                    html += '<li>L' + r.location.row \
+ ': [' + r.code + '] ' + r.message + '</li>';
                }});
                html += '</ul></div>';
            }}

            // Mypy Issues
            if (f.mypy_issues \
&& f.mypy_issues.length > 0) {{
                html += '<div class="detail-item">\
<h5>Type Errors</h5><ul>';
                f.mypy_issues.slice(0, 5).forEach(m => {{
                    html += '<li>L' + m.line \
+ ': ' + m.message + '</li>';
                }});
                html += '</ul></div>';
            }}

            // Bandit Issues
            if (f.bandit_issues \
&& f.bandit_issues.length > 0) {{
                html += '<div class="detail-item">\
<h5>Security Issues</h5><ul>';
                f.bandit_issues.slice(0, 5).forEach(b => {{
                    const sevClass = \
b.issue_severity === 'HIGH' \
? 'complexity-high' : '';
                    html += '<li class="' \
+ sevClass + '">[' + b.issue_severity \
+ '] L' + b.line_number \
+ ': ' + b.issue_text + '</li>';
                }});
                html += '</ul></div>';
            }}

            if (!f.complexity_hotspots?.length \
&& !f.ruff_issues?.length \
&& !f.mypy_issues?.length \
&& !f.bandit_issues?.length) {{
                html += '<div class="detail-item">\
<h5>No Issues</h5>\
<p>This file has good quality</p></div>';
            }}

            html += '</div>';
            return html;
        }}

        function toggleFileDetails(index) {{
            const row = \
event.target.closest('.file-row');
            const details = \
document.getElementById(\
`file-details-${{index}}`);

            // Close others
            document.querySelectorAll(\
'.file-details.active').forEach(d => {{
                if (d !== details) \
d.classList.remove('active');
            }});
            document.querySelectorAll(\
'.file-row.expanded').forEach(r => {{
                if (r !== row) \
r.classList.remove('expanded');
            }});

            details.classList.toggle('active');
            row.classList.toggle('expanded');
        }}

        function filterFiles(filter) {{
            document.querySelectorAll(\
'.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            renderFiles(filter);
        }}

        // Charts
        let gradeChart, complexityChart;

        function initCharts() {{
            const isDark = \
document.body.getAttribute(\
'data-theme') !== 'light';
            const textColor = isDark \
? '#94a3b8' : '#64748b';
            const gridColor = isDark \
? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';

            // Grade Chart
            gradeChart = new Chart(\
document.getElementById('gradeChart'), {{
                type: 'doughnut',
                data: {{
                    labels: \
{json.dumps(grade_labels)},
                    datasets: [{{
                        data: \
{json.dumps(grade_values)},
                        backgroundColor: \
{json.dumps(grade_colors)},
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{ color: textColor }}
                        }}
                    }}
                }}
            }});

            // Complexity Chart
            complexityChart = new Chart(\
document.getElementById('complexityChart'), {{
                type: 'bar',
                data: {{
                    labels: \
{json.dumps(list(complexity_ranges.keys()))},
                    datasets: [{{
                        label: 'Files',
                        data: \
{json.dumps(list(complexity_ranges.values()))},
                        backgroundColor: [\
'#22c55e', '#84cc16', '#eab308', \
'#f97316', '#ef4444'],
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            ticks: {{ color: textColor }},
                            grid: {{ color: gridColor }}
                        }},
                        x: {{
                            ticks: {{ color: textColor }},
                            grid: {{ display: false }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ display: false }}
                    }}
                }}
            }});
        }}

        function updateChartColors() {{
            const isDark = \
document.body.getAttribute(\
'data-theme') !== 'light';
            const textColor = isDark \
? '#94a3b8' : '#64748b';
            const gridColor = isDark \
? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';

            gradeChart.options\
.plugins.legend.labels.color = textColor;
            complexityChart.options\
.scales.y.ticks.color = textColor;
            complexityChart.options\
.scales.y.grid.color = gridColor;
            complexityChart.options\
.scales.x.ticks.color = textColor;

            gradeChart.update();
            complexityChart.update();
        }}

        // Init
        renderFiles();
        initCharts();
    </script>
</body>
</html>"""
        return html

    def _generate_complexity_rows(self, report: ProjectReport) -> str:
        rows = []
        for i, spot in enumerate(report.complexity_hotspots[:10]):
            cc = spot["complexity"]
            css_class = (
                "complexity-high"
                if cc > 20
                else "complexity-medium"
                if cc > 10
                else "complexity-low"
            )
            rel_path = self._relative_path(spot.get("file", ""), report.project_path)
            rows.append(
                f'<tr class="complexity-row"'
                f" onclick="
                f'"toggleComplexityDetail({i})"'
                f' style="cursor: pointer;">'
                f"\n"
                f"    <td>"
                f'<span class="expand-icon">'
                f"&#9654;</span></td>\n"
                f'    <td class="{css_class}">'
                f"{cc}</td>\n"
                f"    <td><code>"
                f"{spot['name']}</code></td>\n"
                f"    <td><code>"
                f"{rel_path}:{spot['line']}"
                f"</code></td>\n"
                f"</tr>\n"
                f'<tr id="complexity-detail-{i}"'
                f' class="complexity-detail-row"'
                f' style="display: none;">\n'
                f'    <td colspan="4">\n'
                f"        <div class="
                f'"complexity-breakdown-panel">\n'
                f"            "
                f"{self._generate_breakdown_content(spot)}"
                f"\n"
                f"        </div>\n"
                f"    </td>\n"
                f"</tr>"
            )
        if rows:
            return "\n".join(rows)
        return "<tr><td colspan='4'>None</td></tr>"

    def _generate_breakdown_content(self, spot: dict) -> str:
        """Generate detailed breakdown for a complexity hotspot."""
        breakdown = spot.get("breakdown", {})

        if not breakdown or breakdown.get("error"):
            return (
                "<p style='color: var(--text-secondary);'>"
                "No detailed breakdown data</p>"
            )

        branch_count = breakdown.get("branch_count", 0)
        calc_cc = breakdown.get(
            "calculated_complexity",
            spot.get("complexity", 0),
        )

        html = (
            '<div style="padding: 1rem;">\n'
            "    <h4"
            ' style="margin: 0 0 0.5rem 0;'
            ' color: var(--text-primary);">'
            "Complexity Calculation</h4>\n"
            '    <p style="color:'
            " var(--text-secondary);"
            ' font-size: 0.9rem;">\n'
            "        Cyclomatic complexity"
            f" = 1 (base) + {branch_count}"
            " (branch points) ="
            ' <strong style="color:'
            ' var(--text-primary);">'
            f"{calc_cc}</strong>\n"
            "    </p>"
        )

        # Branch type statistics
        type_breakdown = breakdown.get("type_breakdown", {})
        if type_breakdown:
            html += (
                '<div style="margin: 0.5rem 0;">'
                "<strong>Branch type breakdown:</strong> "
            )
            type_parts = [f"{k}: {v}" for k, v in type_breakdown.items()]
            html += " | ".join(type_parts) + "</div>"

        # Branch point list
        branches = breakdown.get("branches", [])
        if branches:
            html += (
                '<table style="width: 100%;'
                " font-size: 0.85rem;"
                ' margin-top: 0.5rem;">\n'
                "<thead><tr"
                ' style="border-bottom:'
                ' 1px solid var(--border-color);">\n'
                '    <th style="padding: 0.25rem;'
                ' text-align: left;">Line</th>\n'
                '    <th style="padding: 0.25rem;'
                ' text-align: left;">Type</th>\n'
                '    <th style="padding: 0.25rem;'
                ' text-align: left;">'
                "Description</th>\n"
                "</tr></thead>\n"
                "<tbody>"
            )
            for bp in branches[:20]:  # Show at most 20
                html += (
                    '<tr style="border-bottom:'
                    ' 1px solid var(--border-color);">\n'
                    f'    <td style="padding: 0.25rem;">'
                    f"{bp.get('line', '?')}</td>\n"
                    f'    <td style="padding: 0.25rem;">'
                    f"<code>{bp.get('type', '?')}"
                    f"</code></td>\n"
                    f'    <td style="padding: 0.25rem;">'
                    f"{bp.get('description', '')}</td>\n"
                    f"</tr>"
                )
            html += "</tbody></table>"

            if len(branches) > 20:
                remaining = len(branches) - 20
                html += (
                    '<p style="color:'
                    " var(--text-secondary);"
                    ' font-size: 0.8rem;">'
                    f"... {remaining} more"
                    " branch points</p>"
                )

        html += "</div>"
        return html

    def _generate_complexity_rows_with_expand(self, report: ProjectReport) -> str:
        """Generate expandable complexity hotspot rows."""
        return self._generate_complexity_rows(report)

    def _generate_complexity_details_html(self, report: ProjectReport) -> str:
        """Generate complexity detail hidden areas (integrated into rows)."""
        return ""

    def _generate_security_table(self, report: ProjectReport) -> str:
        if not report.security_hotspots:
            return "<p style='color: #22c55e;'>No security issues</p>"

        rows = []
        for issue in report.security_hotspots[:10]:
            sev = issue.get("issue_severity", "LOW")
            css_class = "complexity-high" if sev == "HIGH" else "complexity-medium"
            rel_path = self._relative_path(issue.get("file", ""), report.project_path)
            rows.append(
                f"<tr>\n"
                f'    <td class="{css_class}">'
                f"{sev}</td>\n"
                f"    <td>"
                f"{issue.get('issue_text', '')[:50]}"
                f"</td>\n"
                f"    <td><code>{rel_path}"
                f":{issue.get('line_number', '?')}"
                f"</code></td>\n"
                f"</tr>"
            )

        return (
            "<table>\n"
            "    <thead><tr>"
            "<th>Severity</th>"
            "<th>Issue</th>"
            "<th>Location</th>"
            "</tr></thead>\n"
            f"    <tbody>{''.join(rows)}</tbody>\n"
            "</table>"
        )

    def _generate_actions_html(self, actions: list) -> str:
        rows = []
        priority_labels = {
            "high": "HIGH",
            "medium": "MEDIUM",
            "low": "LOW",
        }
        for action in actions:
            priority_class = f"priority-{action['priority']}"
            priority_text = priority_labels[action["priority"]]
            rows.append(
                '<div class="action-item">\n'
                f'    <span class="action-priority'
                f" {priority_class}"
                f'">{priority_text}</span>\n'
                f"    <span>{action['text']}</span>\n"
                f"</div>"
            )
        return "\n".join(rows)

    def _generate_files_rows(self, report: ProjectReport) -> str:
        sorted_files = sorted(report.files, key=lambda f: f.score)
        rows = []

        for f in sorted_files[:20]:
            color = self._get_score_color(f.score)
            rel_path = self._relative_path(f.file_path, report.project_path)

            cc_class = (
                "complexity-high"
                if f.max_complexity > 20
                else "complexity-medium"
                if f.max_complexity > 10
                else ""
            )

            rows.append(
                f"<tr>\n"
                f'    <td style="color: {color};'
                f' font-weight: bold;">'
                f"{f.score:.0f}</td>\n"
                f"    <td><code>{rel_path}"
                f"</code></td>\n"
                f'    <td class="{cc_class}">'
                f"{f.max_complexity}</td>\n"
                f"    <td>"
                f"{f.ruff_violations or '-'}</td>\n"
                f"    <td>"
                f"{f.mypy_errors or '-'}</td>\n"
                f"    <td>"
                f"{(f.bandit_high + f.bandit_medium) or '-'}"
                f"</td>\n"
                f"    <td>{f.line_count}</td>\n"
                f"</tr>"
            )

        if len(sorted_files) > 20:
            remaining = len(sorted_files) - 20
            rows.append(
                "<tr>\n"
                '    <td colspan="7"'
                ' style="text-align: center;'
                ' color: #94a3b8;">\n'
                f"        ... {remaining} more files\n"
                "    </td>\n"
                "</tr>"
            )

        return "\n".join(rows)


def generate_report(
    path: str | Path,
    output_format: str = "terminal",
    exclude: Optional[list[str]] = None,
    output_file: Optional[str] = None,
):
    """
    Generate a code quality report.

    Args:
        path: Project path
        output_format: Output format (terminal/json/markdown)
        exclude: Directories to exclude
        output_file: Output file path (optional)
    """
    analyzer = CodeAnalyzer()
    renderer = ReportRenderer()

    # Analyze
    report = analyzer.analyze_project(path, exclude)

    # Render
    if output_format == "json":
        output = renderer.render_json(report)
    elif output_format == "markdown":
        output = renderer.render_markdown(report)
    elif output_format == "html":
        output = renderer.render_html(report)
    else:
        renderer.render_terminal(report)
        return report

    # Output
    if output_file:
        Path(output_file).write_text(output)
        print(f"Report saved to: {output_file}")
    else:
        print(output)

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Python code quality report generator")
    parser.add_argument("path", help="Project path")
    parser.add_argument(
        "-f",
        "--format",
        choices=["terminal", "json", "markdown", "html"],
        default="terminal",
        help="Output format",
    )
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "-e",
        "--exclude",
        nargs="+",
        default=[".venv", "__pycache__", ".git"],
        help="Directories to exclude",
    )

    args = parser.parse_args()
    generate_report(args.path, args.format, args.exclude, args.output)
