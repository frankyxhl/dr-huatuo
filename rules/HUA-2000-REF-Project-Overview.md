# REF-2000: Project Overview

**Applies to:** HUA project
**Last updated:** 2026-03-20
**Last reviewed:** 2026-03-20
**Status:** Active

---

## What Is It?

Huatuo (华佗) is a Python code quality analysis toolkit. It orchestrates multiple static analysis tools (ruff, radon, bandit, mypy, pylint) to produce unified quality reports with scoring and grading.

---

## Content

### Modules

- **code_analyzer.py** — Lightweight single-file analyzer. Runs each tool via subprocess, collects results into `CodeMetrics` dataclass, computes a 0-100 score.
- **code_reporter.py** — Full project analyzer with rich output. Enhanced `CodeAnalyzer` with AST-based complexity breakdown, `ReportRenderer` outputting to terminal/JSON/Markdown/HTML.
- **example_code.py** — Intentionally flawed sample code for demo/testing.

### Required Tools

ruff, radon, bandit, mypy, pylint (all in `.venv`)

### Commands

```bash
python code_analyzer.py <file_or_dir>
python code_reporter.py <path> -f {terminal,json,markdown,html} [-o output_file]
```

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-20 | Initial version | — |
