"""Tests for the analyzer registry and language auto-detection."""

from pathlib import Path

import pytest

from dr_huatuo.analyzers import (
    ANALYZERS,
    BaseAnalyzer,
    LanguageAnalyzer,
    ToolNotFoundError,
    create_analyzer,
    get_analyzer_class,
    register,
)


class DummyAnalyzer(BaseAnalyzer):
    """Minimal analyzer for testing the registry."""

    name = "dummy"
    extensions = [".dum", ".dmy"]
    critical_tools = []
    optional_tools = []

    def __init__(self, project_root=None):
        self.project_root = project_root

    def check_tools(self):
        return {}

    def analyze_file(self, path):
        return {"language": "dummy", "path": str(path)}


class AltAnalyzer(BaseAnalyzer):
    """Alternative analyzer to test overwrite behavior."""

    name = "alt"
    extensions = [".dum"]
    critical_tools = []
    optional_tools = []

    def __init__(self, project_root=None):
        self.project_root = project_root

    def check_tools(self):
        return {}

    def analyze_file(self, path):
        return {"language": "alt"}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate each test from the global ANALYZERS registry."""
    saved = dict(ANALYZERS)
    yield
    ANALYZERS.clear()
    ANALYZERS.update(saved)


class TestRegister:
    def test_register_adds_extensions(self):
        register(DummyAnalyzer)
        assert ANALYZERS[".dum"] is DummyAnalyzer
        assert ANALYZERS[".dmy"] is DummyAnalyzer

    def test_register_overwrites_with_different_class(self):
        register(DummyAnalyzer)
        assert ANALYZERS[".dum"] is DummyAnalyzer
        register(AltAnalyzer)
        assert ANALYZERS[".dum"] is AltAnalyzer


class TestGetAnalyzerClass:
    def test_known_extension(self):
        register(DummyAnalyzer)
        assert get_analyzer_class(".dum") is DummyAnalyzer

    def test_unknown_extension_returns_none(self):
        assert get_analyzer_class(".xyz_unknown") is None


class TestCreateAnalyzer:
    def test_creates_instance(self):
        register(DummyAnalyzer)
        analyzer = create_analyzer(Path("test.dum"))
        assert isinstance(analyzer, DummyAnalyzer)
        assert analyzer.project_root is None

    def test_passes_project_root(self):
        register(DummyAnalyzer)
        root = Path("/some/project")
        analyzer = create_analyzer(Path("test.dum"), project_root=root)
        assert analyzer.project_root == root

    def test_unsupported_extension_returns_none(self):
        assert create_analyzer(Path("test.xyz_unknown")) is None


class TestBaseAnalyzer:
    def test_analyze_batch_delegates_to_analyze_file(self):
        analyzer = DummyAnalyzer()
        paths = [Path("a.dum"), Path("b.dum"), Path("c.dum")]
        results = analyzer.analyze_batch(paths)
        assert len(results) == 3
        assert results[0]["path"] == "a.dum"
        assert results[2]["path"] == "c.dum"

    def test_analyze_batch_empty_list(self):
        analyzer = DummyAnalyzer()
        assert analyzer.analyze_batch([]) == []


class TestProtocol:
    def test_dummy_is_language_analyzer(self):
        assert isinstance(DummyAnalyzer(), LanguageAnalyzer)

    def test_tool_not_found_error_is_exception(self):
        assert issubclass(ToolNotFoundError, Exception)
