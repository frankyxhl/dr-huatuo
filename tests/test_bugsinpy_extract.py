"""Tests for bugsinpy_extract.py.

Covers: bug.info parsing, test file exclusion, multi-file bug handling,
git diff file discovery, manifest schema, skip conditions, and
affected_file extraction.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from bugsinpy_extract import BugExtractionResult, BugsInPyExtractor, ExtractionReport

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_bugsinpy(tmp_path):
    """Create a minimal BugsInPy directory structure."""
    project_dir = tmp_path / "BugsInPy" / "projects" / "thefuck"
    project_dir.mkdir(parents=True)

    # project.info
    (project_dir / "project.info").write_text(
        'github_url="https://github.com/nvbn/thefuck"\nstatus="OK"\n'
    )

    # Bug 1: single-file bug
    bug1 = project_dir / "bugs" / "1"
    bug1.mkdir(parents=True)
    (bug1 / "bug.info").write_text(
        'python_version="3.7.0"\n'
        'buggy_commit_id="aaa111"\n'
        'fixed_commit_id="bbb222"\n'
        'test_file="tests/test_foo.py"\n'
    )

    # Bug 2: multi-file bug
    bug2 = project_dir / "bugs" / "2"
    bug2.mkdir(parents=True)
    (bug2 / "bug.info").write_text(
        'python_version="3.7.0"\n'
        'buggy_commit_id="ccc333"\n'
        'fixed_commit_id="ddd444"\n'
        'test_file="tests/test_bar.py;tests/test_baz.py"\n'
    )

    # Bug 3: no affected .py files (only README changed)
    bug3 = project_dir / "bugs" / "3"
    bug3.mkdir(parents=True)
    (bug3 / "bug.info").write_text(
        'python_version="3.7.0"\n'
        'buggy_commit_id="eee555"\n'
        'fixed_commit_id="fff666"\n'
        'test_file="tests/test_x.py"\n'
    )

    return tmp_path


@pytest.fixture
def extractor(tmp_bugsinpy, tmp_path):
    """Create a BugsInPyExtractor with tmp paths."""
    return BugsInPyExtractor(
        bugsinpy_root=str(tmp_bugsinpy / "BugsInPy"),
        output_root=str(tmp_path / "output"),
        repos_root=str(tmp_path / "repos"),
        project="thefuck",
        exclude_tests=True,
    )


# ---------------------------------------------------------------------------
# ExtractionReport dataclass
# ---------------------------------------------------------------------------


class TestExtractionReport:
    def test_defaults(self):
        r = ExtractionReport()
        assert r.project == ""
        assert r.total_bugs == 0
        assert r.extracted_bugs == 0
        assert r.skipped_bugs == 0
        assert r.total_buggy_files == 0
        assert r.total_fixed_files == 0
        assert r.multi_file_bugs == 0
        assert r.test_files_excluded == 0
        assert r.skip_reasons == {}

    def test_with_values(self):
        r = ExtractionReport(
            project="thefuck",
            total_bugs=32,
            extracted_bugs=28,
            skipped_bugs=4,
        )
        assert r.project == "thefuck"
        assert r.total_bugs == 32


# ---------------------------------------------------------------------------
# BugExtractionResult dataclass
# ---------------------------------------------------------------------------


class TestBugExtractionResult:
    def test_defaults(self):
        r = BugExtractionResult()
        assert r.bug_id == 0
        assert r.buggy_files == []
        assert r.fixed_files == []
        assert r.test_files_excluded == 0
        assert r.is_multi_file is False

    def test_multi_file(self):
        r = BugExtractionResult(
            bug_id=16,
            buggy_files=["a.py", "b.py"],
            fixed_files=["a.py", "b.py"],
            is_multi_file=True,
        )
        assert r.is_multi_file is True
        assert len(r.buggy_files) == 2


# ---------------------------------------------------------------------------
# Test file exclusion
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_test_prefix(self, extractor):
        assert extractor._is_test_file("test_foo.py") is True

    def test_test_suffix(self, extractor):
        assert extractor._is_test_file("foo_test.py") is True

    def test_tests_directory(self, extractor):
        assert extractor._is_test_file("tests/test_foo.py") is True

    def test_nested_tests_directory(self, extractor):
        assert extractor._is_test_file("project/tests/conftest.py") is True

    def test_not_test_file(self, extractor):
        assert extractor._is_test_file("thefuck/rules/pip.py") is False

    def test_test_in_name_but_not_pattern(self, extractor):
        assert extractor._is_test_file("testing_utils.py") is False

    def test_conftest_in_tests_dir(self, extractor):
        assert extractor._is_test_file("tests/conftest.py") is True

    def test_not_py_file(self, extractor):
        assert extractor._is_test_file("test_foo.txt") is False

    def test_source_file_with_test_substring(self, extractor):
        assert extractor._is_test_file("thefuck/contest.py") is False


# ---------------------------------------------------------------------------
# Bug info parsing
# ---------------------------------------------------------------------------


class TestReadBugInfo:
    def test_standard_format(self, extractor, tmp_bugsinpy):
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "1"
        info = extractor._read_bug_info(bug_dir)
        assert info["buggy_commit_id"] == "aaa111"
        assert info["fixed_commit_id"] == "bbb222"
        assert info["python_version"] == "3.7.0"
        assert info["test_file"] == "tests/test_foo.py"

    def test_missing_file(self, extractor, tmp_path):
        info = extractor._read_bug_info(tmp_path / "nonexistent")
        assert info == {}


# ---------------------------------------------------------------------------
# Affected file extraction from path
# ---------------------------------------------------------------------------


class TestExtractAffectedFile:
    def test_standard_path(self, extractor):
        path = "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py"
        result = extractor._extract_affected_file(path, 1, "buggy")
        assert result == "thefuck/rules/pip.py"

    def test_fixed_variant(self, extractor):
        path = "data/bugsinpy/thefuck/fixed/bug_1/thefuck/rules/pip.py"
        result = extractor._extract_affected_file(path, 1, "fixed")
        assert result == "thefuck/rules/pip.py"

    def test_nested_path(self, extractor):
        path = "output/thefuck/buggy/bug_16/thefuck/shells/bash.py"
        result = extractor._extract_affected_file(path, 16, "buggy")
        assert result == "thefuck/shells/bash.py"

    def test_no_match_returns_path(self, extractor):
        path = "some/random/path.py"
        result = extractor._extract_affected_file(path, 1, "buggy")
        assert result == path


# ---------------------------------------------------------------------------
# get_affected_files (mocked subprocess)
# ---------------------------------------------------------------------------


class TestGetAffectedFiles:
    def test_basic(self, extractor, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "thefuck/rules/pip.py\ntests/test_pip.py\nREADME.md\n"
        with patch("bugsinpy_extract.subprocess.run", return_value=mock_result):
            files = extractor._get_affected_files(tmp_path, "aaa", "bbb")
        # Only .py files
        assert "thefuck/rules/pip.py" in files
        assert "tests/test_pip.py" in files
        assert "README.md" not in files

    def test_git_failure(self, extractor, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("bugsinpy_extract.subprocess.run", return_value=mock_result):
            files = extractor._get_affected_files(tmp_path, "aaa", "bbb")
        assert files == []

    def test_empty_diff(self, extractor, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("bugsinpy_extract.subprocess.run", return_value=mock_result):
            files = extractor._get_affected_files(tmp_path, "aaa", "bbb")
        assert files == []

    def test_multi_file(self, extractor, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "thefuck/conf.py\n"
            "thefuck/shells/bash.py\n"
            "thefuck/shells/zsh.py\n"
            "thefuck/shells/__init__.py\n"
        )
        with patch("bugsinpy_extract.subprocess.run", return_value=mock_result):
            files = extractor._get_affected_files(tmp_path, "aaa", "bbb")
        assert len(files) == 4


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestExtractorInit:
    def test_nonexistent_project(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="BugsInPy project not found"):
            BugsInPyExtractor(
                bugsinpy_root=str(tmp_path / "BugsInPy"),
                project="nonexist",
            )

    def test_valid_project(self, tmp_bugsinpy):
        ext = BugsInPyExtractor(
            bugsinpy_root=str(tmp_bugsinpy / "BugsInPy"),
            project="thefuck",
        )
        assert ext.project == "thefuck"
        assert ext.exclude_tests is True


# ---------------------------------------------------------------------------
# _extract_bug (mocked subprocess for git show / git diff)
# ---------------------------------------------------------------------------


class TestExtractBug:
    def test_skip_no_commits(self, extractor, tmp_bugsinpy, tmp_path):
        """Bug with empty commit IDs should be skipped."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "99"
        bug_dir.mkdir(parents=True)
        (bug_dir / "bug.info").write_text(
            'python_version="3.7.0"\nbuggy_commit_id=""\nfixed_commit_id=""\n'
        )
        result = extractor._extract_bug(99, bug_dir, tmp_path)
        assert result is None

    def test_skip_no_py_files(self, extractor, tmp_bugsinpy, tmp_path):
        """Bug with no .py files in diff should be skipped."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "3"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = "README.md\nsetup.cfg\n"

        with patch("bugsinpy_extract.subprocess.run", return_value=diff_result):
            result = extractor._extract_bug(3, bug_dir, tmp_path)
        assert result is None

    def test_skip_all_test_files(self, extractor, tmp_bugsinpy, tmp_path):
        """Bug where all .py files are tests should be skipped."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "1"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = "tests/test_foo.py\ntests/test_bar.py\n"

        with patch("bugsinpy_extract.subprocess.run", return_value=diff_result):
            result = extractor._extract_bug(1, bug_dir, tmp_path)
        assert result is None

    def test_successful_extraction(self, extractor, tmp_bugsinpy, tmp_path):
        """Successful single-file extraction."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "1"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = "thefuck/rules/pip.py\ntests/test_pip.py\n"

        show_result = MagicMock()
        show_result.returncode = 0
        show_result.stdout = b"# buggy/fixed content\n"

        def mock_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "diff":
                return diff_result
            if cmd[0] == "git" and cmd[1] == "show":
                return show_result
            return MagicMock(returncode=1)

        with patch("bugsinpy_extract.subprocess.run", side_effect=mock_run):
            result = extractor._extract_bug(1, bug_dir, tmp_path)

        assert result is not None
        assert result.bug_id == 1
        assert len(result.buggy_files) == 1
        assert len(result.fixed_files) == 1
        assert result.test_files_excluded == 1
        assert result.is_multi_file is False

    def test_multi_file_extraction(self, extractor, tmp_bugsinpy, tmp_path):
        """Multi-file bug extraction."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "2"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = (
            "thefuck/conf.py\nthefuck/shells/bash.py\ntests/test_bar.py\n"
        )

        show_result = MagicMock()
        show_result.returncode = 0
        show_result.stdout = b"# content\n"

        def mock_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "diff":
                return diff_result
            if cmd[0] == "git" and cmd[1] == "show":
                return show_result
            return MagicMock(returncode=1)

        with patch("bugsinpy_extract.subprocess.run", side_effect=mock_run):
            result = extractor._extract_bug(2, bug_dir, tmp_path)

        assert result is not None
        assert result.is_multi_file is True
        assert len(result.buggy_files) == 2
        assert len(result.fixed_files) == 2
        assert result.test_files_excluded == 1

    def test_git_show_failure(self, extractor, tmp_bugsinpy, tmp_path):
        """git show failure for a file should skip that file."""
        bug_dir = tmp_bugsinpy / "BugsInPy" / "projects" / "thefuck" / "bugs" / "1"

        diff_result = MagicMock()
        diff_result.returncode = 0
        diff_result.stdout = "thefuck/rules/pip.py\n"

        show_result = MagicMock()
        show_result.returncode = 128  # git show fails
        show_result.stdout = b""

        def mock_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "diff":
                return diff_result
            if cmd[0] == "git" and cmd[1] == "show":
                return show_result
            return MagicMock(returncode=1)

        with patch("bugsinpy_extract.subprocess.run", side_effect=mock_run):
            result = extractor._extract_bug(1, bug_dir, tmp_path)

        # Both buggy and fixed fail, so result is None
        assert result is None


# ---------------------------------------------------------------------------
# Manifest writing
# ---------------------------------------------------------------------------


class TestWriteManifest:
    def test_writes_jsonl(self, extractor, tmp_path):
        entries = [
            {"bug_id": 1, "path": "a.py", "variant": "buggy"},
            {"bug_id": 2, "path": "b.py", "variant": "buggy"},
        ]
        out_path = tmp_path / "manifest.jsonl"
        extractor._write_manifest(entries, out_path)

        lines = out_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["bug_id"] == 1
        assert json.loads(lines[1])["bug_id"] == 2

    def test_empty_manifest(self, extractor, tmp_path):
        out_path = tmp_path / "manifest.jsonl"
        extractor._write_manifest([], out_path)
        assert out_path.read_text() == ""


# ---------------------------------------------------------------------------
# Manifest schema validation
# ---------------------------------------------------------------------------


class TestManifestSchema:
    def test_manifest_entry_fields(self):
        """Verify manifest entries have all required fields per PRP."""
        entry = {
            "bug_id": 1,
            "project": "thefuck",
            "variant": "buggy",
            "path": "data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py",
            "source": "BugsInPy",
            "license": "MIT",
            "buggy_commit": "aaa111",
            "fixed_commit": "bbb222",
            "affected_file": "thefuck/rules/pip.py",
        }
        required_fields = {
            "bug_id",
            "project",
            "variant",
            "path",
            "source",
            "license",
            "buggy_commit",
            "fixed_commit",
            "affected_file",
        }
        assert set(entry.keys()) == required_fields


# ---------------------------------------------------------------------------
# License mapping
# ---------------------------------------------------------------------------


class TestLicenseMapping:
    def test_thefuck_is_mit(self):
        assert BugsInPyExtractor._PROJECT_LICENSES["thefuck"] == "MIT"

    def test_all_projects_have_licenses(self):
        expected_projects = {
            "thefuck",
            "scrapy",
            "httpie",
            "black",
            "cookiecutter",
            "fastapi",
            "keras",
            "luigi",
            "matplotlib",
            "pandas",
            "PySnooper",
            "sanic",
            "spacy",
            "tornado",
            "tqdm",
            "youtube-dl",
            "ansible",
        }
        assert expected_projects == set(BugsInPyExtractor._PROJECT_LICENSES.keys())


# ---------------------------------------------------------------------------
# Include-tests mode
# ---------------------------------------------------------------------------


class TestIncludeTests:
    def test_include_tests_flag(self, tmp_bugsinpy, tmp_path):
        ext = BugsInPyExtractor(
            bugsinpy_root=str(tmp_bugsinpy / "BugsInPy"),
            output_root=str(tmp_path / "output"),
            repos_root=str(tmp_path / "repos"),
            project="thefuck",
            exclude_tests=False,
        )
        # With exclude_tests=False, test files should NOT be excluded
        assert ext._is_test_file("tests/test_foo.py") is True
        # But the flag means we don't filter them out during extraction
        assert ext.exclude_tests is False
