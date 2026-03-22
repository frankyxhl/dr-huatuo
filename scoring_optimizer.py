"""Scoring formula optimizer for dataset_annotator.py.

Uses scipy.optimize.differential_evolution to find scoring formula weights
that maximize the pair-correct rate (% of BugsInPy pairs where the fixed
file scores higher than the buggy file).

Only optimizes dataset_annotator._calculate_score() weights. Dashboard
formulas in code_analyzer.py and code_reporter.py are not touched.

See HUA-2118-PRP for full specification.

Usage:
    # Full LOPO 4-fold CV
    python scoring_optimizer.py --train thefuck scrapy keras luigi

    # Single held-out
    python scoring_optimizer.py --train thefuck scrapy keras --test luigi

    # Baseline only (no optimization)
    python scoring_optimizer.py \
        --train thefuck scrapy keras --test luigi --baseline-only
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from scipy.optimize import differential_evolution

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path-based pairing regex (same as bugsinpy_analysis.py)
_PAIR_REGEX = re.compile(
    r".*/(?P<variant>buggy|fixed)/bug_(?P<bug_id>\d+)/(?P<affected_file>.+)$"
)

# Parameter order (must match BOUNDS and params tuple)
_PARAM_ORDER = [
    "ruff_weight",
    "ruff_cap",
    "complexity_threshold",
    "complexity_weight",
    "complexity_cap",
    "bandit_high_weight",
    "bandit_high_cap",
    "bandit_medium_weight",
    "bandit_medium_cap",
    "mypy_weight",
    "mypy_cap",
]

# Baseline weights (matching dataset_annotator._calculate_score defaults)
BASELINE_WEIGHTS: dict[str, float] = {
    "ruff_weight": 2,
    "ruff_cap": 30,
    "complexity_threshold": 10,
    "complexity_weight": 5,
    "complexity_cap": 20,
    "bandit_high_weight": 15,
    "bandit_high_cap": 30,
    "bandit_medium_weight": 5,
    "bandit_medium_cap": 15,
    "mypy_weight": 1,
    "mypy_cap": 10,
}

# Search bounds for differential_evolution
BOUNDS: list[tuple[float, float]] = [
    (0, 10),  # ruff_weight
    (10, 50),  # ruff_cap
    (5, 20),  # complexity_threshold
    (1, 15),  # complexity_weight
    (10, 40),  # complexity_cap
    (5, 30),  # bandit_high_weight
    (10, 50),  # bandit_high_cap
    (1, 15),  # bandit_medium_weight
    (5, 30),  # bandit_medium_cap
    (0.5, 5),  # mypy_weight
    (5, 20),  # mypy_cap
]

# All 4 BugsInPy projects used in validation
ALL_PROJECTS = ["thefuck", "scrapy", "keras", "luigi"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OptimizationResult:
    """Result of scoring formula optimization."""

    current_weights: dict
    current_train_pcr: float
    current_test_pcr: Optional[float]
    optimized_weights: dict
    optimized_train_pcr: float
    optimized_test_pcr: Optional[float]
    improvement_train: float
    improvement_test: Optional[float]
    scipy_result: Any


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def _calculate_score_with_params(
    metrics: dict,
    params: tuple,
) -> float:
    """Calculate quality score (0-100) using parameterized weights.

    Args:
        metrics: Dict with ruff_violations, cyclomatic_complexity,
                 bandit_high, bandit_medium, mypy_errors.
        params: Tuple of 11 floats in _PARAM_ORDER order.

    Returns:
        Score between 0 and 100.
    """
    (
        ruff_w,
        ruff_cap,
        cc_thresh,
        cc_w,
        cc_cap,
        bh_w,
        bh_cap,
        bm_w,
        bm_cap,
        mypy_w,
        mypy_cap,
    ) = params

    ruff_violations = metrics.get("ruff_violations") or 0
    cyclomatic_complexity = metrics.get("cyclomatic_complexity") or 0
    bandit_high = metrics.get("bandit_high") or 0
    bandit_medium = metrics.get("bandit_medium") or 0
    mypy_errors = metrics.get("mypy_errors") or 0

    score = 100.0
    score -= min(ruff_violations * ruff_w, ruff_cap)
    if cyclomatic_complexity > cc_thresh:
        score -= min((cyclomatic_complexity - cc_thresh) * cc_w, cc_cap)
    score -= min(bandit_high * bh_w, bh_cap)
    score -= min(bandit_medium * bm_w, bm_cap)
    score -= min(mypy_errors * mypy_w, mypy_cap)
    return max(score, 0.0)


def _pair_correct_rate(
    params: tuple,
    pairs: list[tuple[dict, dict]],
) -> float:
    """Compute pair-correct rate: fraction where fixed scores > buggy.

    Args:
        params: Tuple of 11 weight parameters.
        pairs: List of (buggy_record, fixed_record) tuples.

    Returns:
        Fraction in [0, 1]. Returns 0.0 if pairs is empty.
    """
    if not pairs:
        return 0.0
    correct = 0
    for buggy, fixed in pairs:
        buggy_score = _calculate_score_with_params(buggy, params)
        fixed_score = _calculate_score_with_params(fixed, params)
        if fixed_score > buggy_score:
            correct += 1
    return correct / len(pairs)


def _objective(params: tuple, pairs: list[tuple[dict, dict]]) -> float:
    """Objective function for differential_evolution (minimize).

    Returns negative pair-correct rate.
    """
    return -_pair_correct_rate(params, pairs)


# ---------------------------------------------------------------------------
# Pair loading
# ---------------------------------------------------------------------------


def _load_pairs(
    data_root: str,
    projects: list[str],
) -> list[tuple[dict, dict]]:
    """Load paired (buggy, fixed) records from annotated JSONL files.

    Reconstructs pairs via path-based regex, same as bugsinpy_analysis.py.
    Excludes records with error_type set.

    Args:
        data_root: Root directory containing project subdirectories.
        projects: List of project names to load.

    Returns:
        List of (buggy_record, fixed_record) tuples.
    """
    all_pairs: list[tuple[dict, dict]] = []

    for project in projects:
        project_dir = Path(data_root) / project
        buggy_path = project_dir / "buggy_annotated.jsonl"
        fixed_path = project_dir / "fixed_annotated.jsonl"

        if not buggy_path.exists() or not fixed_path.exists():
            print(
                f"Warning: Missing annotated files for {project} "
                f"in {project_dir}, skipping.",
                file=sys.stderr,
            )
            continue

        buggy_records = _load_jsonl(buggy_path)
        fixed_records = _load_jsonl(fixed_path)

        # Index by (bug_id, affected_file)
        buggy_by_key: dict[tuple[int, str], dict] = {}
        fixed_by_key: dict[tuple[int, str], dict] = {}

        for r in buggy_records:
            parsed = _parse_pairing(r.get("path", ""))
            if parsed is not None:
                bug_id, _variant, affected_file = parsed
                buggy_by_key[(bug_id, affected_file)] = r

        for r in fixed_records:
            parsed = _parse_pairing(r.get("path", ""))
            if parsed is not None:
                bug_id, _variant, affected_file = parsed
                fixed_by_key[(bug_id, affected_file)] = r

        # Join on common keys, exclude error records
        common_keys = set(buggy_by_key.keys()) & set(fixed_by_key.keys())
        for key in sorted(common_keys):
            buggy_r = buggy_by_key[key]
            fixed_r = fixed_by_key[key]
            if (
                buggy_r.get("error_type") is not None
                or fixed_r.get("error_type") is not None
            ):
                continue
            all_pairs.append((buggy_r, fixed_r))

    return all_pairs


def _load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _parse_pairing(path: str) -> tuple[int, str, str] | None:
    """Parse (bug_id, variant, affected_file) from a file path."""
    m = _PAIR_REGEX.search(path)
    if m is None:
        return None
    return (
        int(m.group("bug_id")),
        m.group("variant"),
        m.group("affected_file"),
    )


def _weights_dict_to_params(weights: dict) -> tuple:
    """Convert a weights dict to a params tuple in _PARAM_ORDER order."""
    return tuple(weights[key] for key in _PARAM_ORDER)


def _params_to_weights_dict(params: tuple) -> dict:
    """Convert a params tuple to a weights dict."""
    return {key: round(float(val), 4) for key, val in zip(_PARAM_ORDER, params)}


# ---------------------------------------------------------------------------
# ScoringOptimizer
# ---------------------------------------------------------------------------


class ScoringOptimizer:
    """Optimizes scoring formula weights using BugsInPy paired data."""

    def __init__(
        self,
        data_root: str = "data/bugsinpy",
        train_projects: Optional[list[str]] = None,
        test_projects: Optional[list[str]] = None,
    ) -> None:
        self.data_root = data_root
        self.train_projects = train_projects or ALL_PROJECTS
        self.test_projects = test_projects or []

        self.train_pairs = _load_pairs(data_root, self.train_projects)
        self.test_pairs = (
            _load_pairs(data_root, self.test_projects) if self.test_projects else []
        )

    def optimize(
        self,
        baseline_only: bool = False,
        seed: int = 42,
        maxiter: int = 1000,
        tol: float = 1e-6,
    ) -> OptimizationResult:
        """Run optimization (or baseline-only evaluation).

        Args:
            baseline_only: If True, only compute baseline PCR without optimizing.
            seed: Random seed for differential_evolution.
            maxiter: Maximum iterations for differential_evolution.
            tol: Convergence tolerance for differential_evolution.

        Returns:
            OptimizationResult with before/after comparison.
        """
        baseline_params = _weights_dict_to_params(BASELINE_WEIGHTS)

        # Compute baseline PCR
        current_train_pcr = _pair_correct_rate(baseline_params, self.train_pairs)
        current_test_pcr = (
            _pair_correct_rate(baseline_params, self.test_pairs)
            if self.test_pairs
            else None
        )

        if baseline_only:
            return OptimizationResult(
                current_weights=dict(BASELINE_WEIGHTS),
                current_train_pcr=current_train_pcr,
                current_test_pcr=current_test_pcr,
                optimized_weights=dict(BASELINE_WEIGHTS),
                optimized_train_pcr=current_train_pcr,
                optimized_test_pcr=current_test_pcr,
                improvement_train=0.0,
                improvement_test=0.0 if current_test_pcr is not None else None,
                scipy_result=None,
            )

        # Run optimization
        result = differential_evolution(
            _objective,
            bounds=BOUNDS,
            args=(self.train_pairs,),
            seed=seed,
            maxiter=maxiter,
            tol=tol,
        )

        optimized_params = tuple(result.x)
        optimized_weights = _params_to_weights_dict(optimized_params)

        optimized_train_pcr = _pair_correct_rate(optimized_params, self.train_pairs)
        optimized_test_pcr = (
            _pair_correct_rate(optimized_params, self.test_pairs)
            if self.test_pairs
            else None
        )

        improvement_train = (optimized_train_pcr - current_train_pcr) * 100
        improvement_test = (
            (optimized_test_pcr - current_test_pcr) * 100
            if optimized_test_pcr is not None and current_test_pcr is not None
            else None
        )

        return OptimizationResult(
            current_weights=dict(BASELINE_WEIGHTS),
            current_train_pcr=current_train_pcr,
            current_test_pcr=current_test_pcr,
            optimized_weights=optimized_weights,
            optimized_train_pcr=optimized_train_pcr,
            optimized_test_pcr=optimized_test_pcr,
            improvement_train=improvement_train,
            improvement_test=improvement_test,
            scipy_result=result,
        )


# ---------------------------------------------------------------------------
# LOPO Cross-Validation
# ---------------------------------------------------------------------------


def run_lopo_cv(
    data_root: str = "data/bugsinpy",
    projects: Optional[list[str]] = None,
    seed: int = 42,
    maxiter: int = 1000,
) -> list[OptimizationResult]:
    """Run Leave-One-Project-Out 4-fold cross-validation.

    Each fold holds out one project, optimizes on the other 3,
    and evaluates on the held-out project.

    Args:
        data_root: Root directory for BugsInPy data.
        projects: List of project names (default: ALL_PROJECTS).
        seed: Random seed.
        maxiter: Max iterations per fold.

    Returns:
        List of OptimizationResult, one per fold.
    """
    projects = projects or ALL_PROJECTS
    results: list[OptimizationResult] = []

    for held_out in projects:
        train_projects = [p for p in projects if p != held_out]
        print(f"\n--- Fold: held-out={held_out}, train={train_projects} ---")

        optimizer = ScoringOptimizer(
            data_root=data_root,
            train_projects=train_projects,
            test_projects=[held_out],
        )
        result = optimizer.optimize(seed=seed, maxiter=maxiter)
        results.append(result)

        print(f"  Train pairs: {len(optimizer.train_pairs)}")
        print(f"  Test pairs:  {len(optimizer.test_pairs)}")
        print(f"  Baseline train PCR: {result.current_train_pcr:.1%}")
        print(f"  Baseline test PCR:  {result.current_test_pcr:.1%}")
        print(f"  Optimized train PCR: {result.optimized_train_pcr:.1%}")
        print(f"  Optimized test PCR:  {result.optimized_test_pcr:.1%}")
        print(f"  Improvement (test): {result.improvement_test:+.1f} pp")

    return results


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _render_report(
    result: OptimizationResult,
    train_count: int,
    test_count: Optional[int] = None,
) -> str:
    """Render a single optimization result as a text report."""
    lines: list[str] = []
    lines.append("Scoring Formula Optimization Report")
    lines.append("=" * 36)
    lines.append("")

    lines.append("Current weights:")
    lines.append(
        f"  ruff: -{result.current_weights['ruff_weight']}/violation, "
        f"cap {result.current_weights['ruff_cap']}"
    )
    lines.append(
        f"  complexity: (cc-{result.current_weights['complexity_threshold']})"
        f"*{result.current_weights['complexity_weight']}, "
        f"cap {result.current_weights['complexity_cap']}"
    )
    lines.append(
        f"  bandit_high: -{result.current_weights['bandit_high_weight']}, "
        f"cap {result.current_weights['bandit_high_cap']}"
    )
    lines.append(
        f"  bandit_medium: -{result.current_weights['bandit_medium_weight']}, "
        f"cap {result.current_weights['bandit_medium_cap']}"
    )
    lines.append(
        f"  mypy: -{result.current_weights['mypy_weight']}, "
        f"cap {result.current_weights['mypy_cap']}"
    )
    lines.append("")

    lines.append("Current pair-correct rate:")
    lines.append(f"  Train ({train_count} pairs): {result.current_train_pcr:.1%}")
    if result.current_test_pcr is not None and test_count is not None:
        lines.append(f"  Held-out ({test_count} pairs): {result.current_test_pcr:.1%}")
    lines.append("")

    if result.scipy_result is not None:
        lines.append("Optimized weights:")
        lines.append(
            f"  ruff: -{result.optimized_weights['ruff_weight']}/violation, "
            f"cap {result.optimized_weights['ruff_cap']}"
        )
        lines.append(
            f"  complexity: (cc-{result.optimized_weights['complexity_threshold']})"
            f"*{result.optimized_weights['complexity_weight']}, "
            f"cap {result.optimized_weights['complexity_cap']}"
        )
        lines.append(
            f"  bandit_high: -{result.optimized_weights['bandit_high_weight']}, "
            f"cap {result.optimized_weights['bandit_high_cap']}"
        )
        lines.append(
            f"  bandit_medium: -{result.optimized_weights['bandit_medium_weight']}, "
            f"cap {result.optimized_weights['bandit_medium_cap']}"
        )
        lines.append(
            f"  mypy: -{result.optimized_weights['mypy_weight']}, "
            f"cap {result.optimized_weights['mypy_cap']}"
        )
        lines.append("")

        lines.append("Optimized pair-correct rate:")
        lines.append(f"  Train ({train_count} pairs): {result.optimized_train_pcr:.1%}")
        if result.optimized_test_pcr is not None and test_count is not None:
            lines.append(
                f"  Held-out ({test_count} pairs): {result.optimized_test_pcr:.1%}"
            )
        lines.append("")

        lines.append(f"Improvement: {result.improvement_train:+.1f} pp (train)")
        if result.improvement_test is not None:
            lines.append(f"             {result.improvement_test:+.1f} pp (held-out)")

            if result.improvement_test >= 10:
                lines.append(
                    "Recommendation: UPDATE (>= 10 pp improvement on held-out)"
                )
            else:
                lines.append("Recommendation: KEEP (< 10 pp improvement on held-out)")
        lines.append("")

    return "\n".join(lines)


def _render_lopo_summary(results: list[OptimizationResult]) -> str:
    """Render LOPO cross-validation summary."""
    lines: list[str] = []
    lines.append("")
    lines.append("LOPO Cross-Validation Summary")
    lines.append("=" * 30)
    lines.append("")

    test_improvements = [
        r.improvement_test for r in results if r.improvement_test is not None
    ]
    test_pcrs_baseline = [
        r.current_test_pcr for r in results if r.current_test_pcr is not None
    ]
    test_pcrs_optimized = [
        r.optimized_test_pcr for r in results if r.optimized_test_pcr is not None
    ]

    if test_improvements:
        mean_imp = statistics.mean(test_improvements)
        std_imp = (
            statistics.stdev(test_improvements) if len(test_improvements) > 1 else 0.0
        )
        mean_baseline = statistics.mean(test_pcrs_baseline)
        mean_optimized = statistics.mean(test_pcrs_optimized)

        lines.append(f"Folds: {len(results)}")
        lines.append(f"Mean baseline held-out PCR: {mean_baseline:.1%}")
        lines.append(f"Mean optimized held-out PCR: {mean_optimized:.1%}")
        lines.append(f"Mean improvement: {mean_imp:+.1f} pp (std: {std_imp:.1f} pp)")
        lines.append("")

        if mean_imp >= 10 and std_imp < 10:
            lines.append(
                "RECOMMENDATION: UPDATE weights "
                "(mean improvement >= 10 pp, std < 10 pp)"
            )
        elif mean_imp >= 10:
            lines.append(
                "RECOMMENDATION: REVIEW (mean improvement >= 10 pp but high variance)"
            )
        else:
            lines.append(
                "RECOMMENDATION: KEEP current weights (mean improvement < 10 pp)"
            )
    else:
        lines.append("No held-out results available.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Optimize scoring formula weights using BugsInPy paired data."
    )
    parser.add_argument(
        "--train",
        nargs="+",
        default=ALL_PROJECTS,
        help="Projects to use for training (default: all 4)",
    )
    parser.add_argument(
        "--test",
        nargs="*",
        default=None,
        help="Projects to hold out for testing",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Only compute baseline pair-correct rates without optimizing",
    )
    parser.add_argument(
        "--data-root",
        default="data/bugsinpy",
        help="Root directory for BugsInPy annotated data (default: data/bugsinpy)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for optimizer (default: 42)",
    )
    parser.add_argument(
        "--maxiter",
        type=int,
        default=1000,
        help="Max iterations for differential_evolution (default: 1000)",
    )
    parser.add_argument(
        "--lopo",
        action="store_true",
        help="Run Leave-One-Project-Out 4-fold cross-validation",
    )

    args = parser.parse_args()

    if args.lopo:
        # LOPO mode: ignore --test, use all --train projects
        results = run_lopo_cv(
            data_root=args.data_root,
            projects=args.train,
            seed=args.seed,
            maxiter=args.maxiter,
        )
        print(_render_lopo_summary(results))
    else:
        # Single run mode
        optimizer = ScoringOptimizer(
            data_root=args.data_root,
            train_projects=args.train,
            test_projects=args.test or [],
        )

        result = optimizer.optimize(
            baseline_only=args.baseline_only,
            seed=args.seed,
            maxiter=args.maxiter,
        )

        report = _render_report(
            result,
            train_count=len(optimizer.train_pairs),
            test_count=len(optimizer.test_pairs) if optimizer.test_pairs else None,
        )
        print(report)


if __name__ == "__main__":
    main()
