"""Base protocol, base class, and exceptions for language analyzers."""

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable


class ToolNotFoundError(Exception):
    """Raised when a critical analysis tool is not installed."""


@runtime_checkable
class LanguageAnalyzer(Protocol):
    """Interface that every language analyzer must implement.

    Analyzers may invoke tools via subprocess OR as in-process Python API
    calls (e.g., PythonAnalyzer calls radon and complexipy as libraries).
    The protocol is agnostic to the invocation method.
    """

    name: ClassVar[str]
    extensions: ClassVar[list[str]]
    critical_tools: ClassVar[list[str]]
    optional_tools: ClassVar[list[str]]

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialize with optional project root for tools that need context.

        project_root is required by TypeScript tools (tsc needs tsconfig.json,
        eslint needs .eslintrc). Python tools work per-file and ignore this.
        """
        ...

    def check_tools(self) -> dict[str, str | None]:
        """Verify required tools are available.

        Returns: {tool_name: version_string} for available tools,
                 {tool_name: None} for missing tools.
        Raises ToolNotFoundError if any tool in critical_tools is missing.
        """
        ...

    def analyze_file(self, path: Path) -> dict:
        """Analyze a single file and return the standard metric dict.

        Returns a dict with ALL of these keys (None if not computable):
            cyclomatic_complexity, avg_complexity, cognitive_complexity,
            max_nesting_depth, loc, function_count, class_count,
            maintainability_index, comment_density, docstring_density,
            lint_violations, linter_score, security_high, security_medium,
            type_errors, n1, n2, N1, N2, halstead_volume,
            halstead_difficulty, halstead_effort, language,
            data_warnings, error_type, error_detail, tool_errors.
        """
        ...

    def analyze_batch(self, paths: list[Path]) -> list[dict]:
        """Analyze multiple files in a single invocation.

        Override for languages where tools have high startup cost
        (e.g., Node.js-based tools like eslint, tsc, escomplex).

        Returns: list of metric dicts, one per input path, same order.
        """
        ...


class BaseAnalyzer:
    """Base class with default analyze_batch() implementation.

    Concrete analyzers should inherit from this class (not from the Protocol)
    to get the default batch behavior. The Protocol is for structural typing
    only; this class provides reusable method implementations.
    """

    def analyze_batch(self, paths: list[Path]) -> list[dict]:
        """Default: call analyze_file() per file."""
        return [self.analyze_file(p) for p in paths]
