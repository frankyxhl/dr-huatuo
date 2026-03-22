"""Tests for dataset_annotator.py — TDD RED/GREEN/REFACTOR cycles.

Tests cover:
- Standalone scoring functions (parity with CodeAnalyzer)
- JSONL schema validation (Tier 1 fields)
- Tier 2 fields (--full mode)
- Null semantics (--no-pylint, tool errors)
- Error handling (syntax errors, IO errors, per-tool failures)
- content_sha256 + reproducibility metadata
- AST metrics (loc, class_count, max_nesting_depth, fanout, densities)
- data_warnings heuristics
- annotate_directory and annotate_manifest
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dataset_annotator import (
    ANNOTATOR_VERSION,
    SCHEMA_VERSION,
    DatasetAnnotator,
    _calculate_score,
    _get_grade,
    _normalize_source,
)

# ===================================================================
# Cycle 1: Standalone scoring functions — parity with CodeAnalyzer
# ===================================================================


class TestCalculateScore:
    """Standalone _calculate_score must match CodeAnalyzer formula."""

    def test_all_zeros_score_100(self):
        assert _calculate_score(
            ruff_violations=0,
            cyclomatic_complexity=0,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=0,
        ) == 100.0

    def test_ruff_single_violation(self):
        assert _calculate_score(ruff_violations=1) == 98.0

    def test_ruff_below_cap(self):
        assert _calculate_score(ruff_violations=10) == 80.0

    def test_ruff_at_cap(self):
        assert _calculate_score(ruff_violations=15) == 70.0

    def test_ruff_over_cap(self):
        assert _calculate_score(ruff_violations=20) == 70.0

    def test_complexity_at_10_no_deduction(self):
        assert _calculate_score(cyclomatic_complexity=10) == 100.0

    def test_complexity_11(self):
        assert _calculate_score(cyclomatic_complexity=11) == 95.0

    def test_complexity_below_cap(self):
        assert _calculate_score(cyclomatic_complexity=13) == 85.0

    def test_complexity_at_cap(self):
        assert _calculate_score(cyclomatic_complexity=14) == 80.0

    def test_complexity_over_cap(self):
        assert _calculate_score(cyclomatic_complexity=25) == 80.0

    def test_bandit_high_single(self):
        assert _calculate_score(bandit_high=1) == 85.0

    def test_bandit_high_at_cap(self):
        assert _calculate_score(bandit_high=2) == 70.0

    def test_bandit_high_over_cap(self):
        assert _calculate_score(bandit_high=3) == 70.0

    def test_bandit_medium_single(self):
        assert _calculate_score(bandit_medium=1) == 95.0

    def test_bandit_medium_at_cap(self):
        assert _calculate_score(bandit_medium=3) == 85.0

    def test_bandit_medium_over_cap(self):
        assert _calculate_score(bandit_medium=5) == 85.0

    def test_mypy_single(self):
        assert _calculate_score(mypy_errors=1) == 99.0

    def test_mypy_at_cap(self):
        assert _calculate_score(mypy_errors=10) == 90.0

    def test_mypy_over_cap(self):
        assert _calculate_score(mypy_errors=15) == 90.0

    def test_floor_at_zero(self):
        score = _calculate_score(
            ruff_violations=20,
            cyclomatic_complexity=30,
            bandit_high=3,
            bandit_medium=5,
            mypy_errors=15,
        )
        assert score == 0.0

    def test_combined_deductions(self):
        # ruff: 5*2=10, complexity: (12-10)*5=10, bandit_high: 1*15=15,
        # bandit_medium: 1*5=5, mypy: 3*1=3 => total deductions=43 => 57
        score = _calculate_score(
            ruff_violations=5,
            cyclomatic_complexity=12,
            bandit_high=1,
            bandit_medium=1,
            mypy_errors=3,
        )
        assert score == 57.0


class TestGetGrade:
    """Standalone _get_grade must match CodeAnalyzer grade labels."""

    def test_grade_100(self):
        assert _get_grade(100.0) == "A (Excellent)"

    def test_grade_at_90(self):
        assert _get_grade(90.0) == "A (Excellent)"

    def test_grade_at_89_9(self):
        assert _get_grade(89.9) == "B (Good)"

    def test_grade_at_80(self):
        assert _get_grade(80.0) == "B (Good)"

    def test_grade_at_79_9(self):
        assert _get_grade(79.9) == "C (Fair)"

    def test_grade_at_70(self):
        assert _get_grade(70.0) == "C (Fair)"

    def test_grade_at_69_9(self):
        assert _get_grade(69.9) == "D (Pass)"

    def test_grade_at_60(self):
        assert _get_grade(60.0) == "D (Pass)"

    def test_grade_at_59_9(self):
        assert _get_grade(59.9) == "F (Fail)"

    def test_grade_at_0(self):
        assert _get_grade(0.0) == "F (Fail)"


# ===================================================================
# Cycle 1b: Scoring parity with CodeAnalyzer
# ===================================================================


class TestScoringParity:
    """Verify standalone scoring matches CodeAnalyzer for identical inputs."""

    def test_parity_clean(self):
        from code_analyzer import CodeAnalyzer, CodeMetrics

        analyzer = object.__new__(CodeAnalyzer)
        analyzer.venv_python = None
        m = CodeMetrics(
            file_path="t.py",
            ruff_violations=0,
            max_cyclomatic_complexity=5,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=0,
        )
        ca_score = analyzer._calculate_score(m)
        da_score = _calculate_score(
            ruff_violations=0,
            cyclomatic_complexity=5,
            bandit_high=0,
            bandit_medium=0,
            mypy_errors=0,
        )
        assert ca_score == da_score

    def test_parity_bad(self):
        from code_analyzer import CodeAnalyzer, CodeMetrics

        analyzer = object.__new__(CodeAnalyzer)
        analyzer.venv_python = None
        m = CodeMetrics(
            file_path="t.py",
            ruff_violations=20,
            max_cyclomatic_complexity=30,
            bandit_high=3,
            bandit_medium=5,
            mypy_errors=15,
        )
        ca_score = analyzer._calculate_score(m)
        ca_grade = analyzer._get_grade(ca_score)
        da_score = _calculate_score(
            ruff_violations=20,
            cyclomatic_complexity=30,
            bandit_high=3,
            bandit_medium=5,
            mypy_errors=15,
        )
        da_grade = _get_grade(da_score)
        assert ca_score == da_score
        assert ca_grade == da_grade

    def test_parity_medium(self):
        from code_analyzer import CodeAnalyzer, CodeMetrics

        analyzer = object.__new__(CodeAnalyzer)
        analyzer.venv_python = None
        m = CodeMetrics(
            file_path="t.py",
            ruff_violations=5,
            max_cyclomatic_complexity=12,
            bandit_high=1,
            bandit_medium=2,
            mypy_errors=4,
        )
        ca_score = analyzer._calculate_score(m)
        da_score = _calculate_score(
            ruff_violations=5,
            cyclomatic_complexity=12,
            bandit_high=1,
            bandit_medium=2,
            mypy_errors=4,
        )
        assert ca_score == da_score


# ===================================================================
# Cycle 2: _normalize_source and content_sha256
# ===================================================================


class TestNormalizeSource:
    """Test source normalization for content_sha256."""

    def test_crlf_to_lf(self):
        assert _normalize_source("a\r\nb\r\n") == "a\nb\n"

    def test_strip_trailing_whitespace(self):
        assert _normalize_source("a   \nb  \n") == "a\nb\n"

    def test_combined(self):
        assert _normalize_source("a  \r\nb \r\n") == "a\nb\n"

    def test_empty_string(self):
        assert _normalize_source("") == ""


# ===================================================================
# Cycle 3: Schema validation — Tier 1 fields
# ===================================================================

TIER_1_FIELDS = {
    "schema_version",
    "annotator_version",
    "tool_versions",
    "analysis_config",
    "runtime_env",
    "path",
    "content_sha256",
    "source",
    "license",
    "score",
    "grade",
    "ruff_violations",
    "bandit_high",
    "bandit_medium",
    "mypy_errors",
    "pylint_score",
    "loc",
    "function_count",
    "class_count",
    "cyclomatic_complexity",
    "avg_complexity",
    "cognitive_complexity",
    "max_nesting_depth",
    "n1",
    "n2",
    "N1",
    "N2",
    "halstead_volume",
    "halstead_difficulty",
    "halstead_effort",
    "maintainability_index",
    "fanout_modules",
    "fanout_symbols",
    "comment_density",
    "docstring_density",
    "data_warnings",
    "tool_errors",
    "error_type",
    "error_detail",
}

TIER_2_FIELDS = {
    "lcom4_approx",
    "lcom5_hs",
    "lcom_impl_version",
    "cbo_approx_static",
    "resolved_external_calls",
    "unresolved_dynamic_calls",
    "cbo_resolution_rate",
}


class TestSchemaValidation:
    """Verify Tier 1 schema completeness for annotated records."""

    @pytest.fixture
    def simple_py_file(self, tmp_path):
        """Create a simple Python file for testing."""
        f = tmp_path / "simple.py"
        f.write_text(
            'def hello():\n    """Say hello."""\n    return "hello"\n'
        )
        return f

    @pytest.fixture
    def annotator(self):
        """Create annotator with mocked tool checks."""
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    def test_tier1_fields_present(self, annotator, simple_py_file):
        """All Tier 1 fields must be present in output."""
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(8, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.5, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        assert TIER_1_FIELDS.issubset(
            record.keys()
        ), f"Missing fields: {TIER_1_FIELDS - record.keys()}"

    def test_tier2_fields_absent_without_full(self, annotator, simple_py_file):
        """Tier 2 fields must NOT be present without --full."""
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(8, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.5, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        for field in TIER_2_FIELDS:
            assert field not in record, f"Tier 2 field {field} found without --full"

    def test_schema_version_value(self, annotator, simple_py_file):
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(8, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.5, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        assert record["schema_version"] == SCHEMA_VERSION
        assert record["annotator_version"] == ANNOTATOR_VERSION

    def test_content_sha256_present(self, annotator, simple_py_file):
        """content_sha256 must be computed for readable files."""
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(8, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.5, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        src = simple_py_file.read_text()
        normalized = _normalize_source(src)
        expected_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        assert record["content_sha256"] == expected_hash

    def test_reproducibility_metadata(self, annotator, simple_py_file):
        """runtime_env and analysis_config must be present."""
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(8, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.5, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        assert "runtime_env" in record
        env = record["runtime_env"]
        assert "python_version" in env
        assert "platform" in env
        assert "isolated" in env
        assert env["isolated"] is True

        config = record["analysis_config"]
        assert "run_pylint" in config
        assert "full" in config
        assert "tool_timeout" in config


# ===================================================================
# Cycle 4: Null semantics — no-pylint and tool errors
# ===================================================================


class TestNullSemantics:
    """Verify null semantics per PRP failure contract."""

    @pytest.fixture
    def annotator_no_pylint(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator(run_pylint=False)
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "complexipy": "0.4.0",
                }
                return ann

    @pytest.fixture
    def simple_py_file(self, tmp_path):
        f = tmp_path / "simple.py"
        f.write_text('def hello():\n    """Say hello."""\n    return "hello"\n')
        return f

    def test_pylint_null_when_disabled(self, annotator_no_pylint, simple_py_file):
        """pylint_score must be null (not 0.0) when --no-pylint."""
        with patch.object(
            annotator_no_pylint, "_run_ruff", return_value=(0, None)
        ):
            with patch.object(
                annotator_no_pylint,
                "_run_radon_cc_subprocess",
                return_value=(1, 1, None),
            ):
                with patch.object(
                    annotator_no_pylint, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator_no_pylint, "_run_mypy", return_value=(0, None)
                    ):
                        record = annotator_no_pylint.annotate_file(
                            str(simple_py_file)
                        )
        assert record["pylint_score"] is None

    def test_tool_error_fields_null_on_success(
        self, annotator_no_pylint, simple_py_file
    ):
        """tool_errors must be null when all tools succeed."""
        with patch.object(
            annotator_no_pylint, "_run_ruff", return_value=(0, None)
        ):
            with patch.object(
                annotator_no_pylint,
                "_run_radon_cc_subprocess",
                return_value=(1, 1, None),
            ):
                with patch.object(
                    annotator_no_pylint, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator_no_pylint, "_run_mypy", return_value=(0, None)
                    ):
                        record = annotator_no_pylint.annotate_file(
                            str(simple_py_file)
                        )
        assert record["tool_errors"] is None
        assert record["error_type"] is None
        assert record["error_detail"] is None


# ===================================================================
# Cycle 5: Error handling — syntax errors
# ===================================================================


class TestSyntaxErrorHandling:
    """Files with syntax errors: all metrics null, error_type set."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    @pytest.fixture
    def syntax_error_file(self, tmp_path):
        f = tmp_path / "bad_syntax.py"
        f.write_text("def foo(\n")
        return f

    def test_syntax_error_type(self, annotator, syntax_error_file):
        record = annotator.annotate_file(str(syntax_error_file))
        assert record["error_type"] == "syntax_error"
        assert record["error_detail"] is not None

    def test_syntax_error_metrics_null(self, annotator, syntax_error_file):
        record = annotator.annotate_file(str(syntax_error_file))
        assert record["score"] is None
        assert record["grade"] is None
        assert record["ruff_violations"] is None
        assert record["cyclomatic_complexity"] is None
        assert record["tool_errors"] is None

    def test_syntax_error_sha256_present(self, annotator, syntax_error_file):
        """content_sha256 computed even for syntax errors."""
        record = annotator.annotate_file(str(syntax_error_file))
        assert record["content_sha256"] is not None


# ===================================================================
# Cycle 6: Error handling — IO errors
# ===================================================================


class TestIOErrorHandling:
    """Non-existent files produce io_error records."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    def test_io_error_type(self, annotator):
        record = annotator.annotate_file("/nonexistent/file.py")
        assert record["error_type"] == "io_error"
        assert record["error_detail"] is not None

    def test_io_error_sha256_null(self, annotator):
        """content_sha256 is null when file cannot be read."""
        record = annotator.annotate_file("/nonexistent/file.py")
        assert record["content_sha256"] is None

    def test_io_error_metrics_null(self, annotator):
        record = annotator.annotate_file("/nonexistent/file.py")
        assert record["score"] is None
        assert record["ruff_violations"] is None
        assert record["tool_errors"] is None


# ===================================================================
# Cycle 7: Per-tool failure — tool_errors dict
# ===================================================================


class TestPerToolFailure:
    """Per-tool failures produce partial records with tool_errors dict."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    @pytest.fixture
    def simple_py_file(self, tmp_path):
        f = tmp_path / "simple.py"
        f.write_text('def hello():\n    """Say hello."""\n    return "hello"\n')
        return f

    def test_mypy_timeout_partial_record(self, annotator, simple_py_file):
        """When mypy times out, its fields are null but others succeed."""
        with patch.object(annotator, "_run_ruff", return_value=(3, None)):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                return_value=(5, 2, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 1, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(None, "timeout")
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.0, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        assert record["ruff_violations"] == 3
        assert record["mypy_errors"] is None
        assert record["tool_errors"] is not None
        assert "mypy" in record["tool_errors"]
        assert record["tool_errors"]["mypy"] == "timeout"
        # Score should still be computed with available fields (mypy treated as 0)
        assert record["score"] is not None

    def test_multiple_tool_failures(self, annotator, simple_py_file):
        """Multiple tool failures result in multiple entries in tool_errors."""
        with patch.object(annotator, "_run_ruff", return_value=(None, "crash")):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                return_value=(5, 2, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(None, None, "timeout")
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.0, None)
                        ):
                            record = annotator.annotate_file(
                                str(simple_py_file)
                            )
        assert record["ruff_violations"] is None
        assert record["bandit_high"] is None
        assert record["bandit_medium"] is None
        assert "ruff" in record["tool_errors"]
        assert "bandit" in record["tool_errors"]


# ===================================================================
# Cycle 8: AST metrics
# ===================================================================


class TestASTMetrics:
    """Verify AST-based metric calculations."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    def test_loc_counts_all_lines(self, annotator, tmp_path):
        f = tmp_path / "lines.py"
        f.write_text("a = 1\nb = 2\n\n# comment\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["loc"] == 4

    def test_class_count(self, annotator, tmp_path):
        f = tmp_path / "classes.py"
        f.write_text("class A:\n    pass\n\nclass B:\n    class C:\n        pass\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["class_count"] == 3

    def test_max_nesting_depth_no_control_flow(self, annotator, tmp_path):
        f = tmp_path / "flat.py"
        f.write_text("x = 1\ny = 2\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["max_nesting_depth"] == 0

    def test_max_nesting_depth_nested(self, annotator, tmp_path):
        f = tmp_path / "nested.py"
        f.write_text(
            "def foo():\n"
            "    for i in range(10):\n"
            "        if i > 5:\n"
            "            while True:\n"
            "                break\n"
        )
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(3, 1, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # for -> if -> while = depth 3
        assert record["max_nesting_depth"] == 3

    def test_fanout_modules(self, annotator, tmp_path):
        f = tmp_path / "imports.py"
        f.write_text("import os\nimport os\nfrom os.path import join\nimport sys\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # os, os.path, sys = 3 distinct modules
        assert record["fanout_modules"] == 3

    def test_fanout_symbols(self, annotator, tmp_path):
        f = tmp_path / "symbols.py"
        f.write_text(
            "import os\nfrom os import path, getcwd\nfrom sys import argv\n"
        )
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # path, getcwd, argv = 3 symbols. "import os" has 0 symbols.
        assert record["fanout_symbols"] == 3

    def test_comment_density(self, annotator, tmp_path):
        f = tmp_path / "comments.py"
        f.write_text("# comment1\nx = 1\n# comment2\ny = 2\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # 2 comment lines / 4 total lines = 0.5
        assert record["comment_density"] == pytest.approx(0.5)

    def test_docstring_density(self, annotator, tmp_path):
        f = tmp_path / "docstrings.py"
        f.write_text(
            'def foo():\n    """Doc."""\n    pass\n\n'
            "def bar():\n    pass\n"
        )
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(1, 2, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # 1 out of 2 functions has a docstring
        assert record["docstring_density"] == pytest.approx(0.5)

    def test_empty_file(self, annotator, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["loc"] == 0
        assert record["function_count"] == 0
        assert record["class_count"] == 0
        assert record["comment_density"] == 0.0
        assert record["docstring_density"] == 0.0


# ===================================================================
# Cycle 9: data_warnings heuristics
# ===================================================================


class TestDataWarnings:
    """Verify data_warnings heuristic detection."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    @pytest.fixture
    def big_file(self, tmp_path):
        """File with >20 lines for heuristic triggers."""
        f = tmp_path / "big.py"
        lines = ["# line"] * 25
        f.write_text("\n".join(lines) + "\n")
        return f

    def test_suspect_mypy_env(self, annotator, big_file):
        """mypy_errors / loc > 0.3 triggers suspect:mypy_env."""
        # 25 lines, >0.3 means >7.5 mypy errors => use 10
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                return_value=(0, 0, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(10, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(8.0, None)
                        ):
                            record = annotator.annotate_file(str(big_file))
        assert "suspect:mypy_env" in record["data_warnings"]

    def test_no_warnings_on_clean_file(self, annotator, tmp_path):
        """Clean file should have empty data_warnings."""
        f = tmp_path / "clean.py"
        f.write_text('def hello():\n    """Say hello."""\n    return "hello"\n')
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                return_value=(1, 1, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["data_warnings"] == []

    def test_suspect_radon_on_nontrivial_file(self, annotator, tmp_path):
        """suspect:radon fires: cc==0 and func_count==0 on non-trivial file."""
        # Build a file with >20 lines but no functions (pure assignments)
        lines = ["x = " + str(i) for i in range(25)]
        f = tmp_path / "nontrivial.py"
        f.write_text("\n".join(lines) + "\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                # Radon returns 0 cc and 0 func_count (no functions found)
                return_value=(0, 0, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # File has >20 LOC, cc=0, function_count=0 -> suspect:radon
        assert record["loc"] > 20
        assert record["cyclomatic_complexity"] == 0
        assert record["function_count"] == 0
        assert "suspect:radon" in record["data_warnings"]

    def test_suspect_pylint_when_score_zero(self, annotator, tmp_path):
        """suspect:pylint fires when pylint_score==0.0 and run_pylint=True."""
        f = tmp_path / "zero_pylint.py"
        lines = ["x = " + str(i) for i in range(25)]
        f.write_text("\n".join(lines) + "\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator,
                "_run_radon_cc_subprocess",
                return_value=(1, 1, None),
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(0.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        # pylint_score==0.0 with run_pylint=True -> suspect:pylint
        assert record["pylint_score"] == 0.0
        assert "suspect:pylint" in record["data_warnings"]


# ===================================================================
# Cycle 10: annotate_directory
# ===================================================================


class TestAnnotateDirectory:
    """Test directory traversal and JSONL output."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    @pytest.fixture
    def py_dir(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        (tmp_path / "not_python.txt").write_text("hello\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").write_text("z = 3\n")
        return tmp_path

    def test_finds_all_py_files(self, annotator, py_dir):
        with patch.object(annotator, "annotate_file") as mock_af:
            mock_af.return_value = {"path": "test.py"}
            list(annotator.annotate_directory(str(py_dir)))
        assert mock_af.call_count == 3  # a.py, b.py, sub/c.py

    def test_excludes_directories(self, annotator, py_dir):
        with patch.object(annotator, "annotate_file") as mock_af:
            mock_af.return_value = {"path": "test.py"}
            list(
                annotator.annotate_directory(str(py_dir), exclude=["sub"])
            )
        assert mock_af.call_count == 2  # only a.py and b.py


# ===================================================================
# Cycle 11: annotate_manifest
# ===================================================================


class TestAnnotateManifest:
    """Test JSONL manifest reading."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    def test_manifest_reads_jsonl(self, annotator, tmp_path):
        # Create a python file
        py_file = tmp_path / "sample.py"
        py_file.write_text("x = 1\n")

        # Create manifest with relative path
        manifest = tmp_path / "manifest.jsonl"
        entry = {
            "path": "sample.py",
            "source": "TestSource",
            "license": "MIT",
        }
        manifest.write_text(json.dumps(entry) + "\n")

        with patch.object(annotator, "annotate_file") as mock_af:
            mock_af.return_value = {"path": str(py_file)}
            list(annotator.annotate_manifest(str(manifest)))

        assert mock_af.call_count == 1
        # Check source and license were passed
        call_kwargs = mock_af.call_args
        assert call_kwargs[1]["source"] == "TestSource"
        assert call_kwargs[1]["license"] == "MIT"

    def test_manifest_resolves_relative_paths(self, annotator, tmp_path):
        py_file = tmp_path / "sub" / "code.py"
        py_file.parent.mkdir()
        py_file.write_text("x = 1\n")

        manifest = tmp_path / "manifest.jsonl"
        entry = {"path": "sub/code.py", "source": "S", "license": "L"}
        manifest.write_text(json.dumps(entry) + "\n")

        with patch.object(annotator, "annotate_file") as mock_af:
            mock_af.return_value = {"path": str(py_file)}
            list(annotator.annotate_manifest(str(manifest)))

        called_path = mock_af.call_args[0][0]
        assert Path(called_path).is_absolute()
        assert str(py_file) in called_path


# ===================================================================
# Cycle 12: Source/license propagation
# ===================================================================


class TestSourceLicensePropagation:
    """Verify source and license metadata in output."""

    @pytest.fixture
    def annotator(self):
        with patch.object(DatasetAnnotator, "_check_tools"):
            with patch.object(DatasetAnnotator, "_capture_tool_versions"):
                ann = DatasetAnnotator()
                ann.tool_versions = {
                    "ruff": "0.5.0",
                    "radon": "6.0.1",
                    "bandit": "1.7.9",
                    "mypy": "1.11.0",
                    "pylint": "3.2.6",
                    "complexipy": "0.4.0",
                }
                return ann

    def test_source_license_in_record(self, annotator, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(
                                str(f),
                                source="BugsInPy",
                                license="Apache-2.0",
                            )
        assert record["source"] == "BugsInPy"
        assert record["license"] == "Apache-2.0"

    def test_empty_source_license_defaults(self, annotator, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        with patch.object(annotator, "_run_ruff", return_value=(0, None)):
            with patch.object(
                annotator, "_run_radon_cc_subprocess", return_value=(0, 0, None)
            ):
                with patch.object(
                    annotator, "_run_bandit", return_value=(0, 0, None)
                ):
                    with patch.object(
                        annotator, "_run_mypy", return_value=(0, None)
                    ):
                        with patch.object(
                            annotator, "_run_pylint", return_value=(9.0, None)
                        ):
                            record = annotator.annotate_file(str(f))
        assert record["source"] == ""
        assert record["license"] == ""
