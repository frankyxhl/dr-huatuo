# REF-2112: External Research: Existing Code Quality Tools Survey

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Active

---

## What Is It?

Response from an external research-grade AI surveying existing open-source tools relevant to the HUA-2109-PRP dataset annotation pipeline. Covers all-in-one scanners, orchestration layers, and component-level libraries. Conclusion: no single tool covers the full required schema; a composite pipeline is recommended.

**Related documents:** HUA-2109 (dataset annotator proposal), HUA-2110 (metrics framework), HUA-2111 (metrics research responses)

---

## Content

### All-in-One Quality Scanners

#### Skylos — closest match to requirements
- Covers: cyclomatic complexity, deep nesting, God class, CBO, LCOM1 / LCOM4 / LCOM5
- Output: JSON and SARIF
- CI gate support built in
- Best fit for: batch scan → machine-readable output → quality threshold enforcement
- Source: https://github.com/duriantaco/skylos

#### pyscn — structural quality analyser
- Covers: CBO, cyclomatic complexity, dead code, clone detection
- CLI: `pyscn analyze --json` for machine-readable output; `pyscn check` for quick quality gate
- More focused on structural quality than per-file training data generation
- Source: https://github.com/ludo-technologies/pyscn

#### panoptipy — repository-level rating
- Outputs codebase rating: Gold / Silver / Bronze / Problematic
- Export formats: JSON and parquet
- Limitation: designed for repository-level reports, not per-file training sample generation
- Source: https://aeturrell.github.io/panoptipy/

### Orchestration Layers

#### Prospector — Python-only aggregator
- Bundles: bandit, mypy, pyright, ruff, pylint, pycodestyle, pyflakes, mccabe
- Output: `--output-format json`
- Use case: reduces custom orchestration code when all tools are Python-only
- Does not natively cover Halstead, LCOM, or CBO
- Source: https://prospector.landscape.io/en/master/usage.html

#### MegaLinter — CI/CD dispatcher
- Python linters included: pylint, bandit, mypy, pyright, ruff
- Reporters: JSON and SARIF
- Suited for repository-level CI gates, not for research-grade per-file schema generation
- Source: https://github.com/oxsecurity/megalinter

### Component Libraries (reusable building blocks)

| Library | Purpose | Output | Source |
|---|---|---|---|
| **Radon** | Halstead metrics, cyclomatic complexity, maintainability index, raw metrics | CLI + Python API (`ComplexityVisitor`, `HalsteadVisitor`, Harvester → JSON) | https://radon.readthedocs.io/ |
| **complexipy** | Cognitive Complexity, directory-level analysis | JSON / CSV / SARIF | https://github.com/rohaquinlop/complexipy |
| **inspect4py** | AST structure, CFG, import graph, class/function/call lists | All metadata exported as JSON | https://inspect4py.readthedocs.io/ |
| **lcom** | LCOM4 calculation | Python API | https://pypi.org/project/lcom/ |

**Native machine-readable outputs already available:**

| Tool | Flag |
|---|---|
| Ruff | `--output-format=json` |
| Pylint | `--output-format=json` or `json2` |
| Bandit | `-f json` |
| mypy | `--output json` |

### Conclusion

**No single open-source tool covers the full required combination:** Ruff / Pylint / Bandit / mypy aggregation + Halstead + Cognitive Complexity + LCOM / CBO + per-file JSONL training output.

The existing ecosystem splits into three layers:

| Layer | Tools |
|---|---|
| Orchestration | Prospector, MegaLinter |
| Structural quality metrics | Skylos, pyscn |
| Component libraries | Radon, complexipy, inspect4py, lcom |

**Recommended paths:**

- **Quick evaluation:** Try Skylos first — it covers the widest structural metric set out of the box
- **Research-grade pipeline with controlled schema:** Compose `Ruff + Pylint + Bandit + mypy + Radon + complexipy + inspect4py` — aligns with the composite approach in HUA-2109-PRP

### Impact on HUA-2109-PRP

The survey confirms that `dataset_annotator.py` should not attempt to replicate Skylos or pyscn. Instead:

- Use **Radon** (already integrated) for Halstead and maintainability index
- Add **complexipy** for `cognitive_complexity`
- Add **inspect4py** for structural fields (import graph, call lists) as an alternative to custom AST code
- Add **lcom** package for `lcom4_approx`
- Keep Ruff / Pylint / Bandit / mypy as-is (already integrated)

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | Initial version, translated and structured from external AI tools survey | Claude Code |
