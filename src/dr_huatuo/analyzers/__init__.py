"""Analyzer registry and language auto-detection."""

from pathlib import Path

from dr_huatuo.analyzers.base import BaseAnalyzer, LanguageAnalyzer, ToolNotFoundError

__all__ = [
    "ANALYZERS",
    "BaseAnalyzer",
    "LanguageAnalyzer",
    "ToolNotFoundError",
    "create_analyzer",
    "get_analyzer_class",
    "register",
]

ANALYZERS: dict[str, type[LanguageAnalyzer]] = {}


def register(analyzer_class: type[LanguageAnalyzer]) -> None:
    """Register an analyzer class for its declared file extensions."""
    for ext in analyzer_class.extensions:
        ANALYZERS[ext] = analyzer_class


def get_analyzer_class(ext: str) -> type[LanguageAnalyzer] | None:
    """Return the analyzer class for a file extension, or None."""
    return ANALYZERS.get(ext)


def create_analyzer(
    path: Path, project_root: Path | None = None
) -> LanguageAnalyzer | None:
    """Create an analyzer instance for a file, or None if unsupported."""
    cls = ANALYZERS.get(path.suffix)
    if cls is None:
        return None
    return cls(project_root=project_root)


# Auto-register built-in analyzers (must be after register() definition)
from dr_huatuo.analyzers.python import PythonAnalyzer  # noqa: E402
from dr_huatuo.analyzers.typescript import TypeScriptAnalyzer  # noqa: E402

register(PythonAnalyzer)
register(TypeScriptAnalyzer)
