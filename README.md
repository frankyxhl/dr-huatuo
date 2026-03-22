# dr-huatuo

Code quality diagnosis toolkit for Python. Named after the legendary Chinese physician Hua Tuo (华佗) — it diagnoses code health.

## Features

- **5-Dimension Quality Profile**: Maintainability, Complexity, Code Style, Documentation, Security
- **CI Quality Gate**: `--fail-on D` exits non-zero for CI/CD integration
- **Literature-Backed Thresholds**: McCabe, SonarSource, Microsoft/SEI, with evidence tagging
- **25 Static Metrics**: ruff, radon, bandit, mypy, pylint, complexipy
- **HTML Reports**: Interactive complexity drilldown with source code view

## Quick Start

```bash
pip install dr-huatuo

# Check a file
dr-huatuo check myfile.py

# Check a project with CI quality gate
dr-huatuo check src/ --fail-on D

# Generate HTML report
dr-huatuo report src/ -f html -o report.html
```

## Example Output

```
myfile.py
  Maintainability    A  (MI=65.3)
  Complexity         C  (cognitive_complexity=18 > 15)
  Code Style         A  (ruff=0, pylint=9.2)
  Documentation      B  (docstring_density=0.75)
  Security           PASS

  Action items:
    1. Reduce cognitive complexity (18 → ≤15 for B)
```

## Quality Dimensions

| Dimension | Metrics | Thresholds |
|---|---|---|
| Maintainability | Maintainability Index (MI) | A: ≥40, B: ≥20, C: ≥10, D: <10 |
| Complexity | Cognitive complexity + nesting depth | A: ≤5/≤2, D: >25/≥6 |
| Code Style | ruff violations + pylint score | A: 0 violations + ≥9.0 |
| Documentation | Docstring + comment density | A: ≥80% docstrings + 10-30% comments |
| Security | Bandit HIGH/MEDIUM findings | PASS/WARN/FAIL gate |

## License

MIT
