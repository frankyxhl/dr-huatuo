<p align="center">
  <img src="assets/logo.png" width="200" alt="Huatuo">
</p>

<h1 align="center">dr-huatuo</h1>
<p align="center"><strong>Code Quality Diagnosis Toolkit</strong></p>

<p align="center">
  <em>5-dimension quality profiling for Python. Named after the legendary physician Hua Tuo (华佗) — it diagnoses code health.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/dr-huatuo/"><img src="https://img.shields.io/pypi/v/dr-huatuo" alt="PyPI"></a>
  <a href="https://github.com/frankyxhl/dr-huatuo/actions"><img src="https://img.shields.io/github/actions/workflow/status/frankyxhl/dr-huatuo/ci.yml" alt="CI"></a>
  <img src="https://img.shields.io/pypi/pyversions/dr-huatuo" alt="Python 3.11+">
  <a href="https://github.com/frankyxhl/dr-huatuo/blob/main/LICENSE"><img src="https://img.shields.io/github/license/frankyxhl/dr-huatuo" alt="MIT License"></a>
</p>

---

## What is dr-huatuo?

dr-huatuo orchestrates 6 static analysis tools (ruff, radon, bandit, mypy, pylint, complexipy) into a unified quality profile with 5 independent dimensions. No single aggregate score — each dimension gets its own grade so you know exactly what to fix.

- **5-Dimension Quality Profile** — Maintainability, Complexity, Code Style, Documentation, Security
- **CI Quality Gate** — `--fail-on D` exits non-zero for CI/CD integration
- **Multiple Output Formats** — Terminal (rich), HTML (interactive with Chart.js), JSON, Markdown
- **Literature-Backed Thresholds** — McCabe, SonarSource, Microsoft/SEI, with evidence tagging
- **Plugin Architecture** — Language-agnostic protocol, Python analyzer built-in, TypeScript coming soon

## Quick Start

```bash
pip install dr-huatuo

# Check a file
ht check myfile.py

# Check a project with CI quality gate
ht check src/ --fail-on D

# Generate interactive HTML report
ht report src/ -f html -o report.html

# Show version and tool status
ht version
```

## Example Output

```
src/app.py
  Maintainability    A  (maintainability_index=A)
  Complexity         C  (cognitive_complexity=C, max_nesting_depth=A)
  Code Style         A  (lint_violations=A, linter_score=A)
  Documentation      B  (docstring_density=B, comment_density=A)
  Security           PASS

  Action items:
    1. Reduce cognitive complexity (18 → ≤15 for B)
```

## Quality Dimensions

| Dimension | Metrics | Grades |
|---|---|---|
| **Maintainability** | Maintainability Index (MI) | A: ≥40, B: ≥20, C: ≥10, D: <10 |
| **Complexity** | Cognitive complexity + nesting depth | A: ≤5/≤2, D: >25/≥6 |
| **Code Style** | Lint violations (ruff) + linter score (pylint) | A: 0 violations + ≥9.0 |
| **Documentation** | Docstring + comment density | A: ≥80% docstrings + 10-30% comments |
| **Security** | Bandit HIGH/MEDIUM findings | PASS / WARN / FAIL gate |

Type safety (mypy errors) is reported as informational — not rated.

## CLI Reference

```bash
# Quality check (5-dimension profile)
ht check <path>                          # analyze file or directory
ht check src/ --fail-on D               # CI gate: fail on D or F
ht check src/ --fail-on C               # stricter: fail on C, D, or F
ht check src/ --fail-on WARN            # fail on any security warning
ht check src/ --fail-on D --dimension Security  # gate single dimension
ht check src/ -e .venv tests docs       # exclude directories

# Project reports
ht report <path>                         # terminal output (default)
ht report src/ -f html -o report.html   # interactive HTML with Chart.js
ht report src/ -f json -o report.json   # machine-readable JSON
ht report src/ -f markdown -o report.md # markdown for docs

# Info
ht version                               # show version + tool status
```

## Scoring System

Score starts at 100, with deductions per category:

| Category | Deduction | Cap |
|---|---|---|
| Lint violations | -2 each | -30 |
| Complexity >10 | (cc-10) × 5 | -20 |
| Security HIGH | -15 each | -30 |
| Security MEDIUM | -5 each | -15 |
| Type errors | -1 each | -10 |

Grades: **A** (90+) Excellent, **B** (80+) Good, **C** (70+) Fair, **D** (60+) Pass, **F** (<60) Fail

## Tools Orchestrated

| Tool | What it checks |
|---|---|
| [ruff](https://github.com/astral-sh/ruff) | Lint violations (fast Python linter) |
| [radon](https://github.com/rubik/radon) | Cyclomatic complexity, maintainability index, Halstead metrics |
| [bandit](https://github.com/PyCQA/bandit) | Security vulnerabilities |
| [mypy](https://github.com/python/mypy) | Type errors |
| [pylint](https://github.com/pylint-dev/pylint) | Code quality score |
| [complexipy](https://github.com/rohaquinern/complexipy) | Cognitive complexity |

All tools are installed automatically as dependencies — no manual setup needed.

## Roadmap

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Foundation — single-file analyzer, project reporter, tests, CI/CD, PyPI | Done |
| 2 | Quality Profile & CLI — 5-dimension profile, `ht` CLI, quality gate, HTML drilldown | Done |
| 3 | Scoring Consistency — unified scoring formula, tool detection fix | Done |
| 4 | Analyzer Unification — plugin protocol, `PythonAnalyzer`, generic field names | Done |
| 5 | Multi-Language — TypeScript analyzer, mixed-project support | Planned |
| 6 | Research Pipeline — dataset annotation, deduplication, BugsInPy validation | Done |

## License

MIT
