"""BugsInPy analysis pipeline for huatuo.

Runs annotation + dedup + paired statistical analysis on extracted
BugsInPy file pairs to validate whether huatuo's metrics produce
signals that correlate with known code quality differences.

Usage:
    python bugsinpy_analysis.py --project thefuck

See HUA-2116-PRP for full specification.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dr_huatuo.dataset_annotator import DatasetAnnotator
from dr_huatuo.dataset_dedup import DatasetDeduplicator, DeduplicationReport

# ---------------------------------------------------------------------------
# Path-based pairing regex
# ---------------------------------------------------------------------------

_PAIR_REGEX = re.compile(
    r".*/(?P<variant>buggy|fixed)/bug_(?P<bug_id>\d+)/(?P<affected_file>.+)$"
)

# Numeric metric fields to analyze (from annotator output)
_NUMERIC_METRICS = [
    "score",
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
    "halstead_volume",
    "halstead_difficulty",
    "halstead_effort",
    "maintainability_index",
    "fanout_modules",
    "fanout_symbols",
    "comment_density",
    "docstring_density",
]

# Maximum null rate before excluding a metric (30%)
_NULL_RATE_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PairedResult:
    """Result of paired analysis for a single metric."""

    metric: str = ""
    n_pairs: int = 0
    mean_delta: float = 0.0
    median_delta: float = 0.0
    std_delta: float = 0.0
    pct_fixed_better: float = 0.0
    cohens_d: float = 0.0
    null_rate: float = 0.0
    excluded: bool = False
    exclude_reason: str = ""


@dataclass
class AnalysisReport:
    """Full analysis report."""

    project: str = ""
    # Annotation summary
    total_buggy: int = 0
    total_fixed: int = 0
    buggy_error_rate: float = 0.0
    fixed_error_rate: float = 0.0
    # Score distribution
    buggy_score_stats: dict = field(default_factory=dict)
    fixed_score_stats: dict = field(default_factory=dict)
    # Paired analysis
    paired_results: list[PairedResult] = field(default_factory=list)
    excluded_metrics: list[PairedResult] = field(default_factory=list)
    # Dedup
    within_buggy_dedup: Optional[DeduplicationReport] = None
    within_fixed_dedup: Optional[DeduplicationReport] = None
    cross_split_overlap_rate: float = 0.0
    # Pairing
    total_pairs: int = 0
    unmatched_buggy: int = 0
    unmatched_fixed: int = 0


# ---------------------------------------------------------------------------
# Analysis class
# ---------------------------------------------------------------------------


class BugsInPyAnalysis:
    """Runs annotation + dedup + paired analysis on BugsInPy extractions."""

    def __init__(
        self,
        data_root: str = "data/bugsinpy",
        project: str = "thefuck",
        run_pylint: bool = True,
        tool_timeout: int = 30,
    ) -> None:
        self.data_root = Path(data_root)
        self.project = project
        self.run_pylint = run_pylint
        self.tool_timeout = tool_timeout
        self._project_dir = self.data_root / project

    def run(self) -> AnalysisReport:
        """Run the full analysis pipeline.

        Returns:
            AnalysisReport with all results.
        """
        report = AnalysisReport(project=self.project)

        manifest_buggy = self._project_dir / "manifest_buggy.jsonl"
        manifest_fixed = self._project_dir / "manifest_fixed.jsonl"

        if not manifest_buggy.exists() or not manifest_fixed.exists():
            raise FileNotFoundError(
                f"Manifests not found in {self._project_dir}. "
                f"Run bugsinpy_extract.py first."
            )

        # Step 1-2: Annotate
        buggy_annotated = self._annotate(
            manifest_buggy, self._project_dir / "buggy_annotated.jsonl"
        )
        fixed_annotated = self._annotate(
            manifest_fixed, self._project_dir / "fixed_annotated.jsonl"
        )

        # Load annotated records
        buggy_records = self._load_jsonl(buggy_annotated)
        fixed_records = self._load_jsonl(fixed_annotated)

        report.total_buggy = len(buggy_records)
        report.total_fixed = len(fixed_records)

        # Annotation error rates
        buggy_errors = sum(1 for r in buggy_records if r.get("error_type") is not None)
        fixed_errors = sum(1 for r in fixed_records if r.get("error_type") is not None)
        report.buggy_error_rate = (
            buggy_errors / len(buggy_records) if buggy_records else 0.0
        )
        report.fixed_error_rate = (
            fixed_errors / len(fixed_records) if fixed_records else 0.0
        )

        # Score distribution
        report.buggy_score_stats = self._compute_stats(
            [r.get("score") for r in buggy_records if r.get("score") is not None]
        )
        report.fixed_score_stats = self._compute_stats(
            [r.get("score") for r in fixed_records if r.get("score") is not None]
        )

        # Steps 3-4: Within-split dedup
        buggy_deduped, report.within_buggy_dedup = self._dedup_within(buggy_annotated)
        fixed_deduped, report.within_fixed_dedup = self._dedup_within(fixed_annotated)

        # Step 5: Cross-split overlap (informational only)
        report.cross_split_overlap_rate = self._dedup_cross(
            buggy_annotated, fixed_annotated
        )

        # Step 6: Paired analysis on annotated (pre-dedup) data
        paired_results, excluded, pair_stats = self._paired_analysis(
            buggy_records, fixed_records
        )
        report.paired_results = paired_results
        report.excluded_metrics = excluded
        report.total_pairs = pair_stats["total_pairs"]
        report.unmatched_buggy = pair_stats["unmatched_buggy"]
        report.unmatched_fixed = pair_stats["unmatched_fixed"]

        # Step 7: Generate report
        report_md = self._render_report(report)
        report_path = self._project_dir / "analysis_report.md"
        report_path.write_text(report_md, encoding="utf-8")
        print(f"Report written to {report_path}")

        return report

    # -------------------------------------------------------------------
    # Annotation
    # -------------------------------------------------------------------

    def _annotate(self, manifest_path: Path, output_path: Path) -> Path:
        """Annotate files listed in a manifest.

        Returns:
            Path to the annotated JSONL file.
        """
        annotator = DatasetAnnotator(
            run_pylint=self.run_pylint,
            tool_timeout=self.tool_timeout,
        )

        with open(output_path, "w", encoding="utf-8") as f:
            for record in annotator.annotate_manifest(str(manifest_path)):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return output_path

    # -------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------

    def _dedup_within(self, jsonl_path: Path) -> tuple[Path, DeduplicationReport]:
        """Run within-split deduplication.

        Returns:
            (deduped_path, DeduplicationReport)
        """
        output_path = jsonl_path.with_name(
            jsonl_path.stem.replace("_annotated", "_deduped") + ".jsonl"
        )

        dedup = DatasetDeduplicator(
            threshold=0.8,
            mode="exact",
        )
        report = dedup.deduplicate(
            input_path=str(jsonl_path),
            output_path=str(output_path),
        )
        return output_path, report

    def _dedup_cross(self, buggy_jsonl: Path, fixed_jsonl: Path) -> float:
        """Check cross-split overlap (informational only).

        Returns the overlap rate (dedup_rate when using fixed as ref).
        """
        dedup = DatasetDeduplicator(
            threshold=0.8,
            mode="exact",
        )
        report = dedup.deduplicate(
            input_path=str(buggy_jsonl),
            ref_path=str(fixed_jsonl),
            dry_run=True,
        )
        return report.dedup_rate

    # -------------------------------------------------------------------
    # Paired analysis
    # -------------------------------------------------------------------

    def _paired_analysis(
        self, buggy_records: list[dict], fixed_records: list[dict]
    ) -> tuple[list[PairedResult], list[PairedResult], dict]:
        """Run paired analysis on annotated records.

        Pairs buggy and fixed records by (bug_id, affected_file)
        extracted from the path field via regex.

        Returns:
            (paired_results, excluded_metrics, pair_stats)
        """
        # Parse pairing info from paths
        buggy_by_key: dict[tuple[int, str], dict] = {}
        fixed_by_key: dict[tuple[int, str], dict] = {}

        for r in buggy_records:
            parsed = self._parse_pairing(r.get("path", ""))
            if parsed is not None:
                bug_id, variant, affected_file = parsed
                buggy_by_key[(bug_id, affected_file)] = r

        for r in fixed_records:
            parsed = self._parse_pairing(r.get("path", ""))
            if parsed is not None:
                bug_id, variant, affected_file = parsed
                fixed_by_key[(bug_id, affected_file)] = r

        # Join on (bug_id, affected_file)
        common_keys = set(buggy_by_key.keys()) & set(fixed_by_key.keys())
        unmatched_buggy = len(buggy_by_key) - len(common_keys)
        unmatched_fixed = len(fixed_by_key) - len(common_keys)

        # Build pairs, excluding records with errors
        pairs: list[tuple[dict, dict]] = []
        for key in sorted(common_keys):
            buggy_r = buggy_by_key[key]
            fixed_r = fixed_by_key[key]
            if (
                buggy_r.get("error_type") is not None
                or fixed_r.get("error_type") is not None
            ):
                continue
            pairs.append((buggy_r, fixed_r))

        pair_stats = {
            "total_pairs": len(pairs),
            "unmatched_buggy": unmatched_buggy,
            "unmatched_fixed": unmatched_fixed,
        }

        # Compute deltas for each metric
        results: list[PairedResult] = []
        excluded: list[PairedResult] = []

        for metric in _NUMERIC_METRICS:
            pr = self._compute_paired_metric(metric, pairs)
            if pr.excluded:
                excluded.append(pr)
            else:
                results.append(pr)

        # Sort results by absolute Cohen's d (descending)
        results.sort(key=lambda r: abs(r.cohens_d), reverse=True)

        return results, excluded, pair_stats

    def _parse_pairing(self, path: str) -> tuple[int, str, str] | None:
        """Parse (bug_id, variant, affected_file) from a file path.

        Returns None if the path doesn't match the expected pattern.
        """
        m = _PAIR_REGEX.search(path)
        if m is None:
            return None
        return (
            int(m.group("bug_id")),
            m.group("variant"),
            m.group("affected_file"),
        )

    def _compute_paired_metric(
        self, metric: str, pairs: list[tuple[dict, dict]]
    ) -> PairedResult:
        """Compute paired statistics for a single metric.

        Returns a PairedResult with Cohen's d and other stats.
        """
        deltas: list[float] = []
        null_count = 0

        for buggy_r, fixed_r in pairs:
            buggy_val = buggy_r.get(metric)
            fixed_val = fixed_r.get(metric)

            if buggy_val is None or fixed_val is None:
                null_count += 1
                continue

            try:
                delta = float(fixed_val) - float(buggy_val)
                deltas.append(delta)
            except (TypeError, ValueError):
                null_count += 1

        total = len(pairs)
        null_rate = null_count / total if total > 0 else 1.0

        pr = PairedResult(
            metric=metric,
            null_rate=null_rate,
        )

        # Exclude if null rate too high
        if null_rate > _NULL_RATE_THRESHOLD:
            pr.excluded = True
            pr.exclude_reason = (
                f"null_rate={null_rate:.1%} > {_NULL_RATE_THRESHOLD:.0%}"
            )
            return pr

        if not deltas:
            pr.excluded = True
            pr.exclude_reason = "no valid pairs"
            return pr

        pr.n_pairs = len(deltas)
        pr.mean_delta = statistics.mean(deltas)
        pr.median_delta = statistics.median(deltas)
        pr.std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0

        # Percentage where fixed > buggy (positive delta)
        positive = sum(1 for d in deltas if d > 0)
        pr.pct_fixed_better = positive / len(deltas) if deltas else 0.0

        # Cohen's d = mean(delta) / std(delta)
        if pr.std_delta > 0:
            pr.cohens_d = pr.mean_delta / pr.std_delta
        else:
            # All deltas are the same value
            pr.cohens_d = (
                0.0
                if pr.mean_delta == 0
                else math.copysign(float("inf"), pr.mean_delta)
            )

        return pr

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _load_jsonl(self, path: Path) -> list[dict]:
        """Load records from a JSONL file."""
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def _compute_stats(self, values: list[float]) -> dict:
        """Compute basic statistics for a list of values."""
        if not values:
            return {
                "mean": None,
                "median": None,
                "std": None,
                "min": None,
                "max": None,
                "count": 0,
            }
        return {
            "mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "std": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "count": len(values),
        }

    # -------------------------------------------------------------------
    # Report rendering
    # -------------------------------------------------------------------

    def _render_report(self, report: AnalysisReport) -> str:
        """Render the analysis report as markdown."""
        lines: list[str] = []
        lines.append(f"# BugsInPy Validation Report: {report.project}")
        lines.append("")

        # Extraction / annotation summary
        lines.append("## Annotation Summary")
        lines.append("")
        lines.append(f"- Buggy files annotated: {report.total_buggy}")
        lines.append(f"- Fixed files annotated: {report.total_fixed}")
        lines.append(f"- Buggy error rate: {report.buggy_error_rate:.1%}")
        lines.append(f"- Fixed error rate: {report.fixed_error_rate:.1%}")
        lines.append("")

        # Score distribution
        lines.append("## Score Distribution")
        lines.append("")
        lines.append("| Stat | Buggy | Fixed |")
        lines.append("|------|-------|-------|")
        for stat in ["mean", "median", "std", "min", "max", "count"]:
            bval = report.buggy_score_stats.get(stat, "N/A")
            fval = report.fixed_score_stats.get(stat, "N/A")
            lines.append(f"| {stat} | {bval} | {fval} |")
        lines.append("")

        # Paired analysis
        lines.append("## Paired Metric Deltas")
        lines.append("")
        lines.append(f"Total pairs: {report.total_pairs}")
        lines.append(
            f"Unmatched buggy: {report.unmatched_buggy}, "
            f"unmatched fixed: {report.unmatched_fixed}"
        )
        lines.append("")
        lines.append(
            "| Metric | N | Mean Delta | Median Delta | Cohen's d | % Fixed Better |"
        )
        lines.append(
            "|--------|---|-----------|-------------|----------|----------------|"
        )
        for pr in report.paired_results:
            d_label = self._effect_label(pr.cohens_d)
            lines.append(
                f"| {pr.metric} | {pr.n_pairs} | "
                f"{pr.mean_delta:+.3f} | {pr.median_delta:+.3f} | "
                f"{pr.cohens_d:+.3f} ({d_label}) | "
                f"{pr.pct_fixed_better:.0%} |"
            )
        lines.append("")

        # Top discriminative metrics
        lines.append("## Top Discriminative Metrics (by |Cohen's d|)")
        lines.append("")
        top = [pr for pr in report.paired_results if abs(pr.cohens_d) != float("inf")][
            :5
        ]
        for i, pr in enumerate(top, 1):
            d_label = self._effect_label(pr.cohens_d)
            lines.append(
                f"{i}. **{pr.metric}**: d={pr.cohens_d:+.3f} "
                f"({d_label}), {pr.pct_fixed_better:.0%} fixed better"
            )
        lines.append("")

        # Excluded metrics
        if report.excluded_metrics:
            lines.append("## Excluded Metrics")
            lines.append("")
            for pr in report.excluded_metrics:
                lines.append(f"- **{pr.metric}**: {pr.exclude_reason}")
            lines.append("")

        # Dedup rates
        lines.append("## Near-Duplicate Rates")
        lines.append("")
        if report.within_buggy_dedup:
            lines.append(
                f"- Within-buggy dedup rate: {report.within_buggy_dedup.dedup_rate:.1%}"
            )
        if report.within_fixed_dedup:
            lines.append(
                f"- Within-fixed dedup rate: {report.within_fixed_dedup.dedup_rate:.1%}"
            )
        lines.append(
            f"- Cross-split overlap rate: {report.cross_split_overlap_rate:.1%}"
        )
        lines.append("")

        # Conclusion
        lines.append("## Conclusion")
        lines.append("")
        significant = [
            pr
            for pr in report.paired_results
            if abs(pr.cohens_d) >= 0.2 and abs(pr.cohens_d) != float("inf")
        ]
        if significant:
            lines.append(
                f"**{len(significant)} metrics** show at least small "
                f"effect sizes (|d| >= 0.2), suggesting the pipeline "
                f"produces meaningful quality signals."
            )
            large = [pr for pr in significant if abs(pr.cohens_d) >= 0.8]
            medium = [pr for pr in significant if 0.5 <= abs(pr.cohens_d) < 0.8]
            small = [pr for pr in significant if 0.2 <= abs(pr.cohens_d) < 0.5]
            if large:
                lines.append(f"- Large effects: {', '.join(pr.metric for pr in large)}")
            if medium:
                lines.append(
                    f"- Medium effects: {', '.join(pr.metric for pr in medium)}"
                )
            if small:
                lines.append(f"- Small effects: {', '.join(pr.metric for pr in small)}")
        else:
            lines.append(
                "No metrics show meaningful effect sizes. "
                "Static metrics may not distinguish these bugs."
            )
        lines.append("")

        return "\n".join(lines)

    def _effect_label(self, d: float) -> str:
        """Return effect size label for Cohen's d."""
        ad = abs(d)
        if ad == float("inf"):
            return "infinite"
        if ad >= 0.8:
            return "large"
        if ad >= 0.5:
            return "medium"
        if ad >= 0.2:
            return "small"
        return "negligible"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Run BugsInPy validation analysis")
    parser.add_argument(
        "--project",
        default="thefuck",
        help="BugsInPy project name (default: thefuck)",
    )
    parser.add_argument(
        "--data-root",
        default="data/bugsinpy",
        help="Root directory for extracted data (default: data/bugsinpy)",
    )
    parser.add_argument(
        "--no-pylint",
        action="store_true",
        help="Skip pylint during annotation",
    )
    parser.add_argument(
        "--tool-timeout",
        type=int,
        default=30,
        help="Per-tool timeout in seconds (default: 30)",
    )

    args = parser.parse_args()

    analysis = BugsInPyAnalysis(
        data_root=args.data_root,
        project=args.project,
        run_pylint=not args.no_pylint,
        tool_timeout=args.tool_timeout,
    )

    report = analysis.run()

    # Print summary to terminal
    print(f"\nAnalysis Summary ({report.project}):")
    print(f"  Buggy files:      {report.total_buggy}")
    print(f"  Fixed files:      {report.total_fixed}")
    print(f"  Paired samples:   {report.total_pairs}")
    print(
        f"  Metrics analyzed: "
        f"{len(report.paired_results)} "
        f"({len(report.excluded_metrics)} excluded)"
    )

    if report.paired_results:
        top = report.paired_results[0]
        print(f"  Top metric:       {top.metric} (d={top.cohens_d:+.3f})")


if __name__ == "__main__":
    main()
