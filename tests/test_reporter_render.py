"""Tests for code_reporter.py ReportRenderer.render_json and render_markdown.

Tests verify:
  - render_json: valid JSON, expected top-level keys, file entry keys, empty report
  - render_markdown: expected headers, project path, empty report (no division-by-zero)
"""

import json

import pytest

from dr_huatuo.code_reporter import ReportRenderer


@pytest.fixture
def renderer():
    """Create a ReportRenderer without a real Console."""
    return ReportRenderer()


# ===================================================================
# render_json tests
# ===================================================================


class TestRenderJson:
    """Tests for ReportRenderer.render_json."""

    def test_output_is_valid_json(self, renderer, sample_report):
        output = renderer.render_json(sample_report)
        data = json.loads(output)
        assert isinstance(data, dict)

    def test_top_level_keys(self, renderer, sample_report):
        output = renderer.render_json(sample_report)
        data = json.loads(output)
        expected_keys = {
            "project_path",
            "scan_time",
            "total_files",
            "files",
            "avg_score",
        }
        assert expected_keys.issubset(data.keys())

    def test_file_entry_keys(self, renderer, sample_report):
        output = renderer.render_json(sample_report)
        data = json.loads(output)
        assert len(data["files"]) == 3
        for entry in data["files"]:
            assert "file_path" in entry
            assert "score" in entry
            assert "max_complexity" in entry

    def test_empty_report_valid_json(self, renderer, empty_report):
        output = renderer.render_json(empty_report)
        data = json.loads(output)
        assert data["total_files"] == 0
        assert data["files"] == []

    def test_empty_report_is_valid_json_object(self, renderer, empty_report):
        output = renderer.render_json(empty_report)
        data = json.loads(output)
        assert isinstance(data, dict)


# ===================================================================
# render_markdown tests
# ===================================================================


class TestRenderMarkdown:
    """Tests for ReportRenderer.render_markdown."""

    def test_contains_main_header(self, renderer, sample_report):
        output = renderer.render_markdown(sample_report)
        assert "# Python Code Quality Report" in output

    def test_contains_summary_header(self, renderer, sample_report):
        output = renderer.render_markdown(sample_report)
        assert "## Overall Score" in output

    def test_contains_grade_distribution_header(self, renderer, sample_report):
        output = renderer.render_markdown(sample_report)
        assert "## Grade Distribution" in output

    def test_contains_project_path(self, renderer, sample_report):
        output = renderer.render_markdown(sample_report)
        assert "/project" in output

    def test_contains_score_values(self, renderer, sample_report):
        output = renderer.render_markdown(sample_report)
        # avg_score is 63.0, rendered as "**63**/100" in the summary table
        assert "**63**/100" in output

    def test_empty_report_no_division_by_zero(self, renderer, empty_report):
        """Empty report should render without raising any errors."""
        output = renderer.render_markdown(empty_report)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_empty_report_contains_headers(self, renderer, empty_report):
        """Even an empty report should have the standard headers."""
        output = renderer.render_markdown(empty_report)
        assert "# Python Code Quality Report" in output
        assert "## Overall Score" in output
        assert "## Grade Distribution" in output

    def test_empty_report_has_valid_structure(self, renderer, empty_report):
        """Empty report should still show total_files as 0."""
        output = renderer.render_markdown(empty_report)
        assert "**Files**: 0" in output
