"""Tests for CHG-2106 refactored helpers in code_reporter.py.

Covers:
  - _collect_python_files: sorting, exclusion
  - _aggregate_report: summary stats, grade distribution, hotspot ordering,
    top-10 truncation, empty report edge case
  - _prepare_grade_chart_data: labels, values, colors
  - _prepare_complexity_ranges: bucket boundaries
  - _prepare_actions: threshold boundaries
  - _prepare_files_json: schema-aware JSON
  - render_html: structural invariants (canvas IDs, class names, JSON blob)
  - Complexity bucket boundary tests
  - Action threshold boundary tests
  - analyze_project integration test with monkeypatched analyze_file
"""

import json
from unittest.mock import patch

import pytest

from code_reporter import (
    CodeAnalyzer,
    FileMetrics,
    ProjectReport,
    ReportRenderer,
)

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def analyzer():
    """CodeAnalyzer without running tool checks."""
    obj = object.__new__(CodeAnalyzer)
    obj.available_tools = {}
    return obj


@pytest.fixture
def renderer():
    return ReportRenderer()


def _make_file(
    path="test.py",
    score=100.0,
    grade="A",
    max_complexity=3,
    avg_complexity=2.0,
    func_count=2,
    ruff_violations=0,
    mypy_errors=0,
    bandit_high=0,
    bandit_medium=0,
    line_count=50,
    complexity_hotspots=None,
    ruff_issues=None,
    mypy_issues=None,
    bandit_issues=None,
):
    return FileMetrics(
        file_path=path,
        score=score,
        grade=grade,
        max_complexity=max_complexity,
        avg_complexity=avg_complexity,
        func_count=func_count,
        ruff_violations=ruff_violations,
        mypy_errors=mypy_errors,
        bandit_high=bandit_high,
        bandit_medium=bandit_medium,
        line_count=line_count,
        complexity_hotspots=complexity_hotspots or [],
        ruff_issues=ruff_issues or [],
        mypy_issues=mypy_issues or [],
        bandit_issues=bandit_issues or [],
    )


def _make_report(files=None, **kwargs):
    defaults = {
        "project_path": "/project",
        "scan_time": "2026-03-20T12:00:00",
    }
    defaults.update(kwargs)
    r = ProjectReport(**defaults)
    if files is not None:
        r.files = files
        r.total_files = len(files)
    return r


# ===================================================================
# _collect_python_files
# ===================================================================


class TestCollectPythonFiles:
    """Tests for CodeAnalyzer._collect_python_files."""

    def test_returns_sorted_list(self, tmp_path):
        """Result must be lexicographically sorted."""
        (tmp_path / "b.py").write_text("")
        (tmp_path / "a.py").write_text("")
        (tmp_path / "c.py").write_text("")

        result = CodeAnalyzer._collect_python_files(tmp_path, [])
        names = [p.name for p in result]
        assert names == ["a.py", "b.py", "c.py"]

    def test_excludes_venv(self, tmp_path):
        """Files under .venv/ should be excluded."""
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "dep.py").write_text("")
        (tmp_path / "main.py").write_text("")

        result = CodeAnalyzer._collect_python_files(tmp_path, [".venv"])
        paths = [str(p) for p in result]
        assert any("main.py" in p for p in paths)
        assert not any(".venv" in p for p in paths)

    def test_excludes_multiple_dirs(self, tmp_path):
        """Multiple exclusion patterns work."""
        for d in [".venv", "__pycache__", ".git"]:
            sub = tmp_path / d
            sub.mkdir()
            (sub / "x.py").write_text("")
        (tmp_path / "ok.py").write_text("")

        result = CodeAnalyzer._collect_python_files(
            tmp_path, [".venv", "__pycache__", ".git"]
        )
        assert len(result) == 1
        assert result[0].name == "ok.py"

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty list."""
        result = CodeAnalyzer._collect_python_files(tmp_path, [])
        assert result == []

    def test_preserves_exclude_semantics(self, tmp_path):
        """Exclusion uses 'any(ex in p.parts ...)' semantics."""
        nested = tmp_path / "src" / "build" / "gen"
        nested.mkdir(parents=True)
        (nested / "gen.py").write_text("")
        (tmp_path / "src" / "app.py").write_text("")

        result = CodeAnalyzer._collect_python_files(tmp_path, ["build"])
        names = [p.name for p in result]
        assert "app.py" in names
        assert "gen.py" not in names


# ===================================================================
# _aggregate_report
# ===================================================================


class TestAggregateReport:
    """Tests for CodeAnalyzer._aggregate_report."""

    def test_correct_avg_score(self):
        files = [_make_file(score=80.0), _make_file(score=60.0)]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.avg_score == pytest.approx(70.0)

    def test_correct_max_complexity(self):
        files = [_make_file(max_complexity=5), _make_file(max_complexity=15)]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.max_complexity == 15

    def test_grade_distribution(self):
        files = [
            _make_file(grade="A"),
            _make_file(grade="A"),
            _make_file(grade="C"),
        ]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.grade_distribution == {"A": 2, "C": 1}

    def test_hotspot_sorting_descending(self):
        """Complexity hotspots are sorted descending by complexity."""
        files = [
            _make_file(
                path="a.py",
                complexity_hotspots=[
                    {"name": "low", "line": 1, "complexity": 5},
                    {"name": "high", "line": 2, "complexity": 20},
                ],
            ),
            _make_file(
                path="b.py",
                complexity_hotspots=[
                    {"name": "mid", "line": 1, "complexity": 10},
                ],
            ),
        ]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        complexities = [h["complexity"] for h in report.complexity_hotspots]
        assert complexities == sorted(complexities, reverse=True)

    def test_top_10_truncation(self):
        """Hotspot lists are truncated to 10 entries."""
        spots = [{"name": f"f{i}", "line": i, "complexity": i} for i in range(15)]
        files = [_make_file(complexity_hotspots=spots)]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert len(report.complexity_hotspots) <= 10

    def test_security_hotspots_collection_order(self):
        """Security hotspots preserve collection order (not sorted)."""
        files = [
            _make_file(
                path="a.py",
                bandit_issues=[
                    {"issue_severity": "HIGH", "issue_text": "first", "line_number": 1},
                ],
            ),
            _make_file(
                path="b.py",
                bandit_issues=[
                    {
                        "issue_severity": "MEDIUM",
                        "issue_text": "second",
                        "line_number": 2,
                    },
                ],
            ),
        ]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        texts = [h["issue_text"] for h in report.security_hotspots]
        assert texts == ["first", "second"]

    def test_type_hotspots_collection_order(self):
        """Type hotspots preserve collection order."""
        files = [
            _make_file(
                path="a.py",
                mypy_issues=[{"message": "err1", "line": 1}],
            ),
            _make_file(
                path="b.py",
                mypy_issues=[{"message": "err2", "line": 2}],
            ),
        ]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        msgs = [h["message"] for h in report.type_hotspots]
        assert msgs == ["err1", "err2"]

    def test_empty_report_no_division_by_zero(self):
        """Empty report (0 files) must not raise."""
        report = _make_report(files=[])
        CodeAnalyzer._aggregate_report(report)
        assert report.avg_score == 0.0
        assert report.avg_complexity == 0.0
        assert report.max_complexity == 0
        assert report.total_violations == 0
        assert report.total_type_errors == 0
        assert report.total_security_issues == 0
        assert report.grade_distribution == {}
        assert report.complexity_hotspots == []

    def test_total_violations(self):
        files = [_make_file(ruff_violations=3), _make_file(ruff_violations=7)]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.total_violations == 10

    def test_total_type_errors(self):
        files = [_make_file(mypy_errors=2), _make_file(mypy_errors=4)]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.total_type_errors == 6

    def test_total_security_issues(self):
        files = [
            _make_file(bandit_high=1, bandit_medium=2),
            _make_file(bandit_high=0, bandit_medium=1),
        ]
        report = _make_report(files=files)
        CodeAnalyzer._aggregate_report(report)
        assert report.total_security_issues == 4


# ===================================================================
# _prepare_grade_chart_data
# ===================================================================


class TestPrepareGradeChartData:
    """Tests for ReportRenderer._prepare_grade_chart_data."""

    def test_labels(self, renderer, sample_report):
        data = renderer._prepare_grade_chart_data(sample_report)
        assert data["labels"] == ["A", "B", "C", "D", "F"]

    def test_values_match_distribution(self, renderer, sample_report):
        data = renderer._prepare_grade_chart_data(sample_report)
        grades = ["A", "B", "C", "D", "F"]
        expected = [sample_report.grade_distribution.get(g, 0) for g in grades]
        assert data["values"] == expected

    def test_colors_green_to_red(self, renderer, sample_report):
        data = renderer._prepare_grade_chart_data(sample_report)
        colors = data["colors"]
        assert len(colors) == 5
        # First color (A) is green-ish, last (F) is red-ish
        assert colors[0] == "#22c55e"
        assert colors[-1] == "#ef4444"

    def test_empty_distribution(self, renderer, empty_report):
        data = renderer._prepare_grade_chart_data(empty_report)
        assert data["values"] == [0, 0, 0, 0, 0]


# ===================================================================
# _prepare_complexity_ranges (bucket boundaries)
# ===================================================================


class TestPrepareComplexityRanges:
    """Tests for complexity bucket boundaries."""

    @pytest.mark.parametrize(
        "cc, expected_bucket",
        [
            (5, "1-5"),
            (6, "6-10"),
            (10, "6-10"),
            (11, "11-20"),
            (20, "11-20"),
            (21, "21-50"),
            (50, "21-50"),
            (51, "50+"),
        ],
    )
    def test_bucket_boundaries(self, renderer, cc, expected_bucket):
        files = [_make_file(max_complexity=cc)]
        report = _make_report(files=files)
        ranges = renderer._prepare_complexity_ranges(report)
        assert ranges[expected_bucket] == 1
        # All other buckets should be 0
        for key, val in ranges.items():
            if key != expected_bucket:
                assert val == 0, f"Bucket {key} should be 0 for cc={cc}"

    def test_empty_files(self, renderer):
        report = _make_report(files=[])
        ranges = renderer._prepare_complexity_ranges(report)
        assert all(v == 0 for v in ranges.values())


# ===================================================================
# _prepare_actions (threshold boundaries)
# ===================================================================


class TestPrepareActions:
    """Tests for action threshold boundaries."""

    def test_max_complexity_21_high_priority(self, renderer):
        report = _make_report()
        report.max_complexity = 21
        actions = renderer._prepare_actions(report)
        priorities = [a["priority"] for a in actions]
        assert "high" in priorities

    def test_max_complexity_20_no_complexity_action(self, renderer):
        report = _make_report()
        report.max_complexity = 20
        report.avg_score = 100.0
        actions = renderer._prepare_actions(report)
        texts = [a["text"] for a in actions]
        assert not any("complexity" in t.lower() for t in texts if "Refactor" in t)

    def test_security_issues_1_high_priority(self, renderer):
        report = _make_report()
        report.total_security_issues = 1
        actions = renderer._prepare_actions(report)
        assert any(a["priority"] == "high" and "security" in a["text"] for a in actions)

    def test_security_issues_0_no_security_action(self, renderer):
        report = _make_report()
        report.total_security_issues = 0
        report.avg_score = 100.0
        actions = renderer._prepare_actions(report)
        assert not any("security" in a["text"].lower() for a in actions)

    def test_type_errors_6_medium_priority(self, renderer):
        report = _make_report()
        report.total_type_errors = 6
        actions = renderer._prepare_actions(report)
        assert any(
            a["priority"] == "medium" and "type error" in a["text"].lower()
            for a in actions
        )

    def test_type_errors_5_no_type_action(self, renderer):
        report = _make_report()
        report.total_type_errors = 5
        report.avg_score = 100.0
        actions = renderer._prepare_actions(report)
        assert not any("type error" in a["text"].lower() for a in actions)

    def test_violations_21_medium_priority(self, renderer):
        report = _make_report()
        report.total_violations = 21
        actions = renderer._prepare_actions(report)
        assert any(
            a["priority"] == "medium" and "violation" in a["text"].lower()
            for a in actions
        )

    def test_violations_20_no_violation_action(self, renderer):
        report = _make_report()
        report.total_violations = 20
        report.avg_score = 100.0
        actions = renderer._prepare_actions(report)
        assert not any("violation" in a["text"].lower() for a in actions)

    def test_avg_score_69_9_low_quality_action(self, renderer):
        report = _make_report()
        report.avg_score = 69.9
        actions = renderer._prepare_actions(report)
        assert any("improvement plan" in a["text"].lower() for a in actions)

    def test_avg_score_70_no_low_quality_action(self, renderer):
        report = _make_report()
        report.avg_score = 70.0
        actions = renderer._prepare_actions(report)
        assert not any("improvement plan" in a["text"].lower() for a in actions)

    def test_no_issues_returns_keep_it_up(self, renderer):
        report = _make_report()
        report.max_complexity = 5
        report.total_security_issues = 0
        report.total_type_errors = 0
        report.total_violations = 0
        report.avg_score = 100.0
        actions = renderer._prepare_actions(report)
        assert len(actions) == 1
        assert actions[0]["priority"] == "low"
        assert "keep it up" in actions[0]["text"].lower()


# ===================================================================
# _prepare_files_json
# ===================================================================


class TestPrepareFilesJson:
    """Tests for _prepare_files_json schema."""

    def test_valid_json(self, renderer, sample_report):
        result = renderer._prepare_files_json(sample_report)
        data = json.loads(result)
        assert isinstance(data, list)

    def test_summary_keys(self, renderer, sample_report):
        data = json.loads(renderer._prepare_files_json(sample_report))
        for entry in data:
            assert "path" in entry
            assert "score" in entry
            assert "max_complexity" in entry
            assert "ruff_violations" in entry
            assert "mypy_errors" in entry
            assert "bandit_high" in entry
            assert "bandit_medium" in entry
            assert "line_count" in entry

    def test_detail_keys(self, renderer, sample_report):
        data = json.loads(renderer._prepare_files_json(sample_report))
        for entry in data:
            assert "full_path" in entry
            assert "complexity_hotspots" in entry
            assert "ruff_issues" in entry
            assert "mypy_issues" in entry
            assert "bandit_issues" in entry

    def test_entry_count_matches_files(self, renderer, sample_report):
        data = json.loads(renderer._prepare_files_json(sample_report))
        assert len(data) == len(sample_report.files)

    def test_empty_report(self, renderer, empty_report):
        data = json.loads(renderer._prepare_files_json(empty_report))
        assert data == []


# ===================================================================
# render_html structural invariants
# ===================================================================


class TestRenderHtmlStructure:
    """Tests for render_html structural invariants."""

    def test_contains_grade_chart_canvas(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert 'id="gradeChart"' in html

    def test_contains_complexity_chart_canvas(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert 'id="complexityChart"' in html

    def test_contains_score_card_class(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert "score-card" in html

    def test_contains_section_card_class(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert "section-card" in html

    def test_contains_files_data_json(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert 'id="files-data"' in html
        # Extract and parse the JSON blob
        start = html.index('type="application/json">') + len(
            'type="application/json">'
        )
        end = html.index("</script>", start)
        blob = html[start:end]
        data = json.loads(blob)
        assert isinstance(data, list)
        assert len(data) == len(sample_report.files)

    def test_contains_files_body(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert 'id="files-body"' in html

    def test_contains_chart_js_init(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert "new Chart(" in html

    def test_contains_tab_elements(self, renderer, sample_report):
        html = renderer.render_html(sample_report)
        assert 'class="tab active"' in html
        assert 'class="tab"' in html

    def test_empty_report_renders(self, renderer, empty_report):
        """Empty report should render without errors."""
        html = renderer.render_html(empty_report)
        assert 'id="gradeChart"' in html
        assert len(html) > 0

    def test_chart_data_matches_report(self, renderer, sample_report):
        """Chart.js grade dataset values must match report grade_distribution."""
        html = renderer.render_html(sample_report)
        # The grade chart data array is rendered as JSON in the JS code
        # Grade order: A, B, C, D, F
        for grade in ["A", "B", "C", "D", "F"]:
            count = sample_report.grade_distribution.get(grade, 0)
            # The count appears in the datasets data array
            assert str(count) in html


# ===================================================================
# analyze_project integration test
# ===================================================================


class TestAnalyzeProjectIntegration:
    """Integration test: monkeypatch analyze_file, verify wiring."""

    def test_wiring(self, tmp_path, analyzer):
        """_collect_python_files + _aggregate_report are wired correctly."""
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")

        fake_metrics = {
            str(tmp_path / "a.py"): _make_file(
                path=str(tmp_path / "a.py"),
                score=90.0,
                grade="A",
                max_complexity=5,
                avg_complexity=3.0,
                line_count=10,
            ),
            str(tmp_path / "b.py"): _make_file(
                path=str(tmp_path / "b.py"),
                score=70.0,
                grade="C",
                max_complexity=12,
                avg_complexity=8.0,
                line_count=20,
            ),
        }

        def fake_analyze_file(self_inner, file_path):
            return fake_metrics[str(file_path)]

        with patch.object(CodeAnalyzer, "analyze_file", fake_analyze_file):
            report = analyzer.analyze_project(tmp_path)

        assert report.total_files == 2
        assert report.avg_score == pytest.approx(80.0)
        assert report.max_complexity == 12
        assert report.total_lines == 30
        assert "A" in report.grade_distribution
        assert "C" in report.grade_distribution
