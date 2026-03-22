"""Shared fixtures for huatuo test suite."""

import pytest

from dr_huatuo.code_analyzer import CodeMetrics
from dr_huatuo.code_reporter import FileMetrics, ProjectReport

# ---------------------------------------------------------------------------
# CodeMetrics fixtures (code_analyzer.py)
# Field for complexity: max_cyclomatic_complexity
# ---------------------------------------------------------------------------


@pytest.fixture
def zero_code_metrics():
    """CodeMetrics with all values at defaults (0)."""
    return CodeMetrics(file_path="test.py")


@pytest.fixture
def clean_code_metrics():
    """CodeMetrics with no violations — score should be 100."""
    return CodeMetrics(
        file_path="test.py",
        max_cyclomatic_complexity=5,
        functions_analyzed=3,
        ruff_violations=0,
        mypy_errors=0,
        bandit_high=0,
        bandit_medium=0,
    )


@pytest.fixture
def bad_code_metrics():
    """CodeMetrics with high violations across all dimensions."""
    return CodeMetrics(
        file_path="test.py",
        max_cyclomatic_complexity=30,
        functions_analyzed=10,
        ruff_violations=20,
        mypy_errors=15,
        bandit_high=3,
        bandit_medium=5,
    )


# ---------------------------------------------------------------------------
# FileMetrics fixtures (code_reporter.py)
# Field for complexity: max_complexity
# ---------------------------------------------------------------------------


@pytest.fixture
def zero_file_metrics():
    """FileMetrics with all values at defaults (0)."""
    return FileMetrics(file_path="test.py")


@pytest.fixture
def clean_file_metrics():
    """FileMetrics with no violations — score should be 100."""
    return FileMetrics(
        file_path="test.py",
        max_complexity=5,
        avg_complexity=3.0,
        func_count=3,
        ruff_violations=0,
        mypy_errors=0,
        bandit_high=0,
        bandit_medium=0,
    )


@pytest.fixture
def bad_file_metrics():
    """FileMetrics with high violations across all dimensions."""
    return FileMetrics(
        file_path="test.py",
        max_complexity=30,
        avg_complexity=15.0,
        func_count=10,
        ruff_violations=20,
        mypy_errors=15,
        bandit_high=3,
        bandit_medium=5,
    )


# ---------------------------------------------------------------------------
# ProjectReport fixtures (code_reporter.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_report():
    """ProjectReport with 3 FileMetrics of varying scores."""
    files = [
        FileMetrics(
            file_path="/project/good.py",
            max_complexity=3,
            avg_complexity=2.0,
            func_count=5,
            ruff_violations=0,
            mypy_errors=0,
            bandit_high=0,
            bandit_medium=0,
            line_count=100,
            score=100.0,
            grade="A",
        ),
        FileMetrics(
            file_path="/project/medium.py",
            max_complexity=12,
            avg_complexity=8.0,
            func_count=4,
            ruff_violations=5,
            mypy_errors=2,
            bandit_high=0,
            bandit_medium=1,
            line_count=200,
            score=69.0,
            grade="D",
        ),
        FileMetrics(
            file_path="/project/bad.py",
            max_complexity=25,
            avg_complexity=15.0,
            func_count=3,
            ruff_violations=10,
            mypy_errors=8,
            bandit_high=1,
            bandit_medium=2,
            line_count=150,
            score=20.0,
            grade="F",
        ),
    ]
    return ProjectReport(
        project_path="/project",
        scan_time="2026-03-20T12:00:00",
        total_files=3,
        total_lines=450,
        total_functions=12,
        avg_score=63.0,
        avg_complexity=8.3,
        max_complexity=25,
        total_violations=15,
        total_type_errors=10,
        total_security_issues=4,
        grade_distribution={"A": 1, "D": 1, "F": 1},
        files=files,
    )


@pytest.fixture
def empty_report():
    """ProjectReport with 0 files."""
    return ProjectReport(
        project_path="/empty",
        scan_time="2026-03-20T12:00:00",
        total_files=0,
        total_lines=0,
        total_functions=0,
        avg_score=0.0,
        avg_complexity=0.0,
        max_complexity=0,
        total_violations=0,
        total_type_errors=0,
        total_security_issues=0,
        grade_distribution={},
        files=[],
    )
