"""
Python code quality analyzer.
Supports multi-dimensional quality analysis of single files or directories.
"""

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class CodeMetrics:
    """Code metrics data structure."""

    file_path: str

    # Complexity
    max_cyclomatic_complexity: int = 0
    functions_analyzed: int = 0

    # Lint
    ruff_violations: int = 0
    ruff_errors: list[Any] = field(default_factory=list)
    pylint_score: float = 0.0

    # Types
    mypy_errors: int = 0
    mypy_warnings: list[Any] = field(default_factory=list)

    # Security
    bandit_high: int = 0
    bandit_medium: int = 0
    bandit_issues: list[Any] = field(default_factory=list)

    # Overall grade
    overall_score: float = 0.0
    grade: str = "N/A"

    def to_dict(self) -> dict:
        return asdict(self)


class CodeAnalyzer:
    """Python code quality analyzer."""

    def __init__(self, venv_python: Optional[str] = None):
        """
        Initialize the analyzer.

        Args:
            venv_python: Path to venv Python, e.g. ".venv/bin/python"
        """
        self.venv_python = venv_python
        self._check_tools()

    def _check_tools(self):
        """Check that required tools are installed."""
        required = ["ruff", "radon", "bandit", "mypy", "pylint"]
        missing = []

        for tool in required:
            result = subprocess.run(
                ["which", tool],
                capture_output=True,
            )
            if result.returncode != 0:
                missing.append(tool)

        if missing:
            print(
                f"Warning: the following tools are not installed: {', '.join(missing)}"
            )
            print("Run: pip install ruff radon bandit mypy pylint")

    def analyze(self, path: str | Path, run_pylint: bool = True) -> CodeMetrics:
        """
        Analyze a code file or directory.

        Args:
            path: File or directory path
            run_pylint: Whether to run pylint (slower)

        Returns:
            CodeMetrics object
        """
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {resolved}")

        metrics = CodeMetrics(file_path=str(resolved))

        # 1. Ruff (fastest)
        ruff_result = self._run_ruff(resolved)
        metrics.ruff_violations = len(ruff_result)
        metrics.ruff_errors = ruff_result[:10]  # Keep only first 10

        # 2. Radon complexity
        complexity_data = self._run_radon(resolved)
        metrics.max_cyclomatic_complexity = complexity_data.get("max", 0)
        metrics.functions_analyzed = complexity_data.get("count", 0)

        # 3. Bandit security scan
        bandit_result = self._run_bandit(resolved)
        metrics.bandit_high = sum(
            1 for r in bandit_result if r.get("issue_severity") == "HIGH"
        )
        metrics.bandit_medium = sum(
            1 for r in bandit_result if r.get("issue_severity") == "MEDIUM"
        )
        metrics.bandit_issues = bandit_result[:5]  # Keep only first 5

        # 4. Mypy type checking
        mypy_result = self._run_mypy(resolved)
        metrics.mypy_errors = len(mypy_result)
        metrics.mypy_warnings = mypy_result[:10]  # Keep only first 10

        # 5. Pylint (optional, slower)
        if run_pylint:
            metrics.pylint_score = self._run_pylint(resolved)

        # Calculate overall score
        metrics.overall_score = self._calculate_score(metrics)
        metrics.grade = self._get_grade(metrics.overall_score)

        return metrics

    def _run_ruff(self, path: Path) -> list:
        """Run ruff check."""
        try:
            result = subprocess.run(
                ["ruff", "check", str(path), "--output-format=json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout:
                return json.loads(result.stdout)
        except Exception as e:
            print(f"Ruff error: {e}")
        return []

    def _run_radon(self, path: Path) -> dict:
        """Run radon complexity analysis."""
        try:
            result = subprocess.run(
                ["radon", "cc", str(path), "-j"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                all_funcs = []
                for _file_path, funcs in data.items():
                    all_funcs.extend(funcs)

                if all_funcs:
                    complexities = [f.get("complexity", 0) for f in all_funcs]
                    return {
                        "max": max(complexities),
                        "avg": sum(complexities) / len(complexities),
                        "count": len(all_funcs),
                    }
        except Exception as e:
            print(f"Radon error: {e}")
        return {"max": 0, "avg": 0, "count": 0}

    def _run_bandit(self, path: Path) -> list:
        """Run bandit security scan."""
        try:
            result = subprocess.run(
                ["bandit", "-r", str(path), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                return data.get("results", [])
        except Exception as e:
            print(f"Bandit error: {e}")
        return []

    def _run_mypy(self, path: Path) -> list:
        """Run mypy type checking."""
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
        except Exception as e:
            print(f"Mypy error: {e}")
        return []

    def _run_pylint(self, path: Path) -> float:
        """Run pylint and extract score."""
        try:
            result = subprocess.run(
                ["pylint", str(path), "--output-format=parseable"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Extract score from output
            output = result.stdout + result.stderr
            match = re.search(r"rated at ([\d.]+)/10", output)
            if match:
                return float(match.group(1))
        except Exception as e:
            print(f"Pylint error: {e}")
        return 0.0

    def _calculate_score(self, metrics: CodeMetrics) -> float:
        """Calculate overall score (0-100)."""
        score = 100.0

        # Ruff violations: -2 each, capped at 30
        score -= min(metrics.ruff_violations * 2, 30)

        # Complexity: deduct when >10, -5 each, capped at 20
        if metrics.max_cyclomatic_complexity > 10:
            score -= min((metrics.max_cyclomatic_complexity - 10) * 5, 20)

        # Security: HIGH -15 each (cap 30), MEDIUM -5 each (cap 15)
        score -= min(metrics.bandit_high * 15, 30)
        score -= min(metrics.bandit_medium * 5, 15)

        # Type errors: -1 each, capped at 10
        score -= min(metrics.mypy_errors, 10)

        return max(score, 0)

    def _get_grade(self, score: float) -> str:
        """Get grade label from score."""
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


def print_report(metrics: CodeMetrics):
    """Print analysis report."""
    print("=" * 60)
    print("Code Quality Analysis Report")
    print("=" * 60)
    print(f"File: {metrics.file_path}")
    print()

    print(f"{'Dimension':<20} {'Result':<30} {'Status':<10}")
    print("-" * 60)

    # Overall score
    print(f"{'Overall Score':<20} {metrics.overall_score:.1f}/100 ({metrics.grade})")
    print()

    # Ruff
    status = "OK" if metrics.ruff_violations == 0 else "WARN"
    print(f"{'Ruff Violations':<20} {metrics.ruff_violations} {status}")

    # Complexity
    status = "OK" if metrics.max_cyclomatic_complexity <= 10 else "WARN"
    print(
        f"{'Max Complexity':<20} "
        f"{metrics.max_cyclomatic_complexity} (threshold<=10) {status}"
    )

    # Security
    status = "OK" if metrics.bandit_high == 0 else "ALERT"
    print(f"{'Security HIGH':<20} {metrics.bandit_high} {status}")
    print(f"{'Security MEDIUM':<20} {metrics.bandit_medium}")

    # Types
    status = "OK" if metrics.mypy_errors == 0 else "WARN"
    print(f"{'Type Errors':<20} {metrics.mypy_errors} {status}")

    # Pylint
    if metrics.pylint_score > 0:
        status = "OK" if metrics.pylint_score >= 8 else "WARN"
        print(f"{'Pylint Score':<20} {metrics.pylint_score:.1f}/10 {status}")

    print()

    # Detailed issues
    if metrics.bandit_high > 0:
        print("ALERT - Security HIGH issues:")
        for issue in metrics.bandit_issues[:3]:
            if issue.get("issue_severity") == "HIGH":
                print(f"   - L{issue['line_number']}: {issue['issue_text']}")
        print()

    if metrics.ruff_errors:
        print("WARN - Ruff violation details:")
        for err in metrics.ruff_errors[:5]:
            print(f"   - L{err['location']['row']}: [{err['code']}] {err['message']}")
        print()

    print("=" * 60)


def review_code(path: str, verbose: bool = True) -> CodeMetrics:
    """
    Convenience function: analyze code and print report.

    Args:
        path: File or directory path
        verbose: Whether to print detailed report

    Returns:
        CodeMetrics object
    """
    analyzer = CodeAnalyzer()
    metrics = analyzer.analyze(path)

    if verbose:
        print_report(metrics)

    return metrics


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python code_analyzer.py <file_or_directory>")
        print("Example: python code_analyzer.py ./my_code.py")
        sys.exit(1)

    path = sys.argv[1]
    review_code(path)
