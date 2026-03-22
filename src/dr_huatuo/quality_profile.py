"""Multi-dimensional code quality profile.

Evaluates Python files across 5 independent dimensions, each with a
separate rating. No aggregate score. Every threshold is tagged with
its evidence level in the PRP (HUA-2122).

Dimensions:
  1. Maintainability — based on maintainability_index (MI) only
  2. Complexity — worst of cognitive_complexity and max_nesting_depth
  3. Code Style — worst of ruff_violations and pylint_score
  4. Documentation — worst of docstring_density and comment_density
  5. Security — PASS/WARN/FAIL gate (not A-D)

Type Safety (mypy_errors) is informational only, not rated.
"""

from dataclasses import dataclass

# Rating order for worst-of comparisons (D is worst, A is best)
_RATING_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass
class DimensionResult:
    """Result for a single quality dimension."""

    name: str
    rating: str | None  # A/B/C/D or PASS/WARN/FAIL or None (N/A)
    limiting_metric: str | None
    detail: dict[str, str | int | float]


@dataclass
class QualityProfile:
    """Complete quality profile across all 5 dimensions."""

    maintainability: DimensionResult
    complexity: DimensionResult
    code_style: DimensionResult
    documentation: DimensionResult
    security: DimensionResult
    mypy_errors: int | None
    mypy_env_sensitive: bool
    summary: str

    def to_flat_dict(self) -> dict:
        """Convert profile to flat dict with qp_* prefixed keys.

        Suitable for merging into annotator output records.
        """
        result: dict = {}

        for dim in (
            self.maintainability,
            self.complexity,
            self.code_style,
            self.documentation,
            self.security,
        ):
            prefix = f"qp_{dim.name}"
            result[prefix] = dim.rating
            result[f"{prefix}_limiting"] = dim.limiting_metric
            result[f"{prefix}_detail"] = dict(dim.detail)

        result["qp_mypy_errors"] = self.mypy_errors
        result["qp_mypy_env_sensitive"] = self.mypy_env_sensitive
        result["qp_summary"] = self.summary

        return result


def _rate_single_mi(mi: float) -> str:
    """Rate a maintainability_index value to A/B/C/D."""
    if mi >= 40:
        return "A"
    elif mi >= 20:
        return "B"
    elif mi >= 10:
        return "C"
    else:
        return "D"


def _rate_single_cognitive(cc: int) -> str:
    """Rate cognitive_complexity to A/B/C/D."""
    if cc <= 5:
        return "A"
    elif cc <= 15:
        return "B"
    elif cc <= 25:
        return "C"
    else:
        return "D"


def _rate_single_nesting(depth: int) -> str:
    """Rate max_nesting_depth to A/B/C/D."""
    if depth <= 2:
        return "A"
    elif depth == 3:
        return "B"
    elif depth <= 5:
        return "C"
    else:
        return "D"


def _rate_single_ruff(violations: int) -> str:
    """Rate ruff_violations to A/B/C/D."""
    if violations == 0:
        return "A"
    elif violations <= 3:
        return "B"
    elif violations <= 10:
        return "C"
    else:
        return "D"


def _rate_single_pylint(score: float) -> str:
    """Rate pylint_score to A/B/C/D."""
    if score >= 9.0:
        return "A"
    elif score >= 7.0:
        return "B"
    elif score >= 5.0:
        return "C"
    else:
        return "D"


def _rate_single_docstring(density: float) -> str:
    """Rate docstring_density to A/B/C/D."""
    if density >= 0.80:
        return "A"
    elif density >= 0.50:
        return "B"
    elif density >= 0.20:
        return "C"
    else:
        return "D"


def _rate_single_comment(density: float) -> str:
    """Rate comment_density to A/B/C/D.

    A: >=0.10 and <=0.30
    B: (>=0.05 and <0.10) or (>0.30 and <=0.40)
    C: >=0.01 and <0.05
    D: <0.01 or >0.40
    """
    if 0.10 <= density <= 0.30:
        return "A"
    elif (0.05 <= density < 0.10) or (0.30 < density <= 0.40):
        return "B"
    elif 0.01 <= density < 0.05:
        return "C"
    else:
        return "D"


def _worst_rating(ratings: list[tuple[str, str]]) -> tuple[str, str | None]:
    """Find the worst rating among (metric_name, rating) pairs.

    Returns (worst_rating, limiting_metric_name).
    limiting_metric is None if the worst rating is A (nothing limiting).
    """
    if not ratings:
        return "A", None

    worst = ratings[0]
    for item in ratings[1:]:
        if _RATING_ORDER[item[1]] > _RATING_ORDER[worst[1]]:
            worst = item

    limiting = worst[0] if worst[1] != "A" else None
    return worst[1], limiting


def _rate_maintainability(mi: float | None) -> DimensionResult:
    """Rate the Maintainability dimension based on MI."""
    if mi is None:
        return DimensionResult(
            name="maintainability", rating=None, limiting_metric=None, detail={}
        )

    rating = _rate_single_mi(mi)
    limiting = "maintainability_index" if rating != "A" else None
    return DimensionResult(
        name="maintainability",
        rating=rating,
        limiting_metric=limiting,
        detail={"maintainability_index": rating},
    )


def _rate_complexity(cognitive: int | None, nesting: int | None) -> DimensionResult:
    """Rate the Complexity dimension (worst of cognitive + nesting)."""
    ratings: list[tuple[str, str]] = []
    detail: dict[str, str] = {}

    if cognitive is not None:
        r = _rate_single_cognitive(cognitive)
        ratings.append(("cognitive_complexity", r))
        detail["cognitive_complexity"] = r

    if nesting is not None:
        r = _rate_single_nesting(nesting)
        ratings.append(("max_nesting_depth", r))
        detail["max_nesting_depth"] = r

    if not ratings:
        return DimensionResult(
            name="complexity", rating=None, limiting_metric=None, detail={}
        )

    worst, limiting = _worst_rating(ratings)
    return DimensionResult(
        name="complexity", rating=worst, limiting_metric=limiting, detail=detail
    )


def _rate_code_style(ruff: int | None, pylint: float | None) -> DimensionResult:
    """Rate the Code Style dimension (worst of ruff + pylint)."""
    ratings: list[tuple[str, str]] = []
    detail: dict[str, str] = {}

    if ruff is not None:
        r = _rate_single_ruff(ruff)
        ratings.append(("ruff_violations", r))
        detail["ruff_violations"] = r

    if pylint is not None:
        r = _rate_single_pylint(pylint)
        ratings.append(("pylint_score", r))
        detail["pylint_score"] = r

    if not ratings:
        return DimensionResult(
            name="code_style", rating=None, limiting_metric=None, detail={}
        )

    worst, limiting = _worst_rating(ratings)
    return DimensionResult(
        name="code_style", rating=worst, limiting_metric=limiting, detail=detail
    )


def _rate_documentation(
    docstring_d: float | None,
    comment_d: float | None,
    function_count: int | None,
    loc: int | None,
) -> DimensionResult:
    """Rate the Documentation dimension.

    Edge cases:
    - function_count == 0: docstring_density excluded
    - loc == 0: comment_density excluded
    - metric is None: excluded
    """
    ratings: list[tuple[str, str]] = []
    detail: dict[str, str] = {}

    # Docstring density: exclude if function_count is 0 or None, or value is None
    include_docstring = (
        docstring_d is not None and function_count is not None and function_count > 0
    )
    if include_docstring:
        r = _rate_single_docstring(docstring_d)  # type: ignore[arg-type]
        ratings.append(("docstring_density", r))
        detail["docstring_density"] = r

    # Comment density: exclude if loc is 0 or None, or value is None
    include_comment = comment_d is not None and loc is not None and loc > 0
    if include_comment:
        r = _rate_single_comment(comment_d)  # type: ignore[arg-type]
        ratings.append(("comment_density", r))
        detail["comment_density"] = r

    if not ratings:
        return DimensionResult(
            name="documentation", rating=None, limiting_metric=None, detail={}
        )

    worst, limiting = _worst_rating(ratings)
    return DimensionResult(
        name="documentation", rating=worst, limiting_metric=limiting, detail=detail
    )


def _rate_security(
    bandit_high: int | None, bandit_medium: int | None
) -> DimensionResult:
    """Rate the Security dimension (PASS/WARN/FAIL gate).

    PASS: high=0 AND medium<=2
    WARN: high=0 AND medium>2
    FAIL: high>=1
    """
    detail: dict[str, int] = {}

    if bandit_high is not None:
        detail["bandit_high"] = bandit_high
    if bandit_medium is not None:
        detail["bandit_medium"] = bandit_medium

    # If high >= 1, always FAIL (even if medium is null)
    if bandit_high is not None and bandit_high >= 1:
        return DimensionResult(
            name="security",
            rating="FAIL",
            limiting_metric="bandit_high",
            detail=detail,
        )

    # Need both metrics to determine PASS/WARN
    if bandit_high is None or bandit_medium is None:
        return DimensionResult(
            name="security", rating=None, limiting_metric=None, detail=detail
        )

    # high == 0
    if bandit_medium <= 2:
        return DimensionResult(
            name="security",
            rating="PASS",
            limiting_metric=None,
            detail=detail,
        )
    else:
        return DimensionResult(
            name="security",
            rating="WARN",
            limiting_metric="bandit_medium",
            detail=detail,
        )


def _build_summary(qp: "QualityProfile") -> str:
    """Build compact one-line summary string.

    Format: M:A Cx:C St:B Doc:D Sec:PASS
    Null dimensions are excluded.
    """
    parts: list[str] = []

    dim_abbrevs = [
        (qp.maintainability, "M"),
        (qp.complexity, "Cx"),
        (qp.code_style, "St"),
        (qp.documentation, "Doc"),
        (qp.security, "Sec"),
    ]

    for dim, abbrev in dim_abbrevs:
        if dim.rating is not None:
            parts.append(f"{abbrev}:{dim.rating}")

    return " ".join(parts)


def profile_file(metrics: dict) -> QualityProfile:
    """Generate a quality profile from annotated metrics.

    Args:
        metrics: Dict from dataset_annotator with metric fields.

    Returns:
        QualityProfile with all 5 dimensions rated.
    """
    maintainability = _rate_maintainability(metrics.get("maintainability_index"))
    complexity = _rate_complexity(
        cognitive=metrics.get("cognitive_complexity"),
        nesting=metrics.get("max_nesting_depth"),
    )
    code_style = _rate_code_style(
        ruff=metrics.get("ruff_violations"),
        pylint=metrics.get("pylint_score"),
    )
    documentation = _rate_documentation(
        docstring_d=metrics.get("docstring_density"),
        comment_d=metrics.get("comment_density"),
        function_count=metrics.get("function_count"),
        loc=metrics.get("loc"),
    )
    security = _rate_security(
        bandit_high=metrics.get("bandit_high"),
        bandit_medium=metrics.get("bandit_medium"),
    )

    mypy_errors = metrics.get("mypy_errors")
    data_warnings = metrics.get("data_warnings", [])
    mypy_env_sensitive = "suspect:mypy_env" in data_warnings

    qp = QualityProfile(
        maintainability=maintainability,
        complexity=complexity,
        code_style=code_style,
        documentation=documentation,
        security=security,
        mypy_errors=mypy_errors,
        mypy_env_sensitive=mypy_env_sensitive,
        summary="",  # placeholder
    )
    qp.summary = _build_summary(qp)

    return qp
