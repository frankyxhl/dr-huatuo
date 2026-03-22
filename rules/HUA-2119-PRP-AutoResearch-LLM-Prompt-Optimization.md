# PRP-2119: AutoResearch LLM Prompt Optimization (Phase 3)

**Applies to:** HUA project
**Last updated:** 2026-03-22
**Last reviewed:** 2026-03-22
**Status:** Draft
**Related:** HUA-2118-PRP (Scoring Optimizer), HUA-2116-PRP (BugsInPy Validation)
**Reviewed by:** —

---

## Background

HUA-2118-PRP uses `scipy.optimize` to find better scoring formula weights — a pure numeric optimization problem. However, Phase 3 may involve **LLM-based code quality assessment**: given a Python file and/or its static metrics, an LLM classifies or scores the code. This introduces a **text optimization problem** (prompt wording, metric selection, output format, few-shot examples) that numeric optimizers cannot handle.

[AutoResearch](https://github.com/olelehmann100kMRR/autoresearch-skill) is a Claude Code skill designed for exactly this: iterative binary-eval prompt mutation. It was incorrectly proposed for numeric weight optimization in HUA-2118 v1 (rejected by Gemini 4/10). This PRP positions it for its correct use case: **LLM prompt optimization**.

---

## What Is It?

Integration of the AutoResearch skill to optimize LLM-based code quality assessment prompts in Phase 3. The skill takes a quality assessment prompt, runs it against BugsInPy paired data, scores outputs via binary eval criteria, and iteratively mutates the prompt to improve classification accuracy.

---

## Problem

### 1. LLM prompts are sensitive to wording

Small changes in prompt wording ("Is this code buggy?" vs "Rate the quality of this code on a scale of 1-10" vs "Compare these metrics and classify...") can dramatically change LLM output quality. Manual prompt engineering is slow, subjective, and hard to reproduce.

### 2. Metric selection for prompts is non-trivial

Phase 2 showed 8+ metrics carry signal. Which ones to include in a quality assessment prompt? Including all 21 adds noise; including too few misses signal. The optimal subset depends on prompt structure and LLM behavior — a search problem.

### 3. AutoResearch is designed for this

Its binary-eval + mutation loop is specifically built for text/prompt optimization, not numeric parameters. This is the correct tool for the correct problem.

---

## Scope

**In scope:**
- Install AutoResearch skill (pinned to specific commit hash)
- Create a `huatuo-quality-prompt` optimization target
- Binary evals: "Does the LLM correctly classify the fixed file as higher quality than the buggy file?"
- Run optimization on BugsInPy paired data
- Output: optimized quality assessment prompt + accuracy metrics

**Out of scope:**
- Scoring formula weight optimization (HUA-2118 — scipy, already separate)
- Training custom ML models
- Deploying the optimized prompt as a production service

**Prerequisites (must be completed before this PRP is implemented):**
- HUA-2118-PRP implemented (optimized scoring weights provide a stronger baseline)
- BugsInPy data extracted for ≥ 4 projects (already done)
- Decision on which LLM to use for quality assessment (Claude? GPT? open-source?)

---

## Proposed Solution

### Step 1: Install AutoResearch

```bash
# Pin to specific commit for reproducibility
git clone https://github.com/olelehmann100kMRR/autoresearch-skill.git \
  ~/.claude/skills/autoresearch
cd ~/.claude/skills/autoresearch
git checkout <pinned-commit-hash>  # pin after verifying license + stability
```

**Dependency risk mitigation:** AutoResearch is a single-commit, pre-alpha repo. Fallback plan: if the skill breaks or is abandoned, the core loop (mutate prompt → run on test cases → score → keep/discard) can be reimplemented as a simple Python script (~100 lines). The mutation strategy is straightforward; the skill is a convenience, not a hard dependency.

### Step 2: Create quality assessment prompt target

```markdown
# huatuo-quality-prompt skill

You are a code quality assessor. Given two Python code metrics records
(from huatuo static analysis), determine which represents higher quality code.

Record A metrics:
{metrics_a}

Record B metrics:
{metrics_b}

Which record represents higher quality code? Answer "A" or "B" only.
```

### Step 3: Binary eval criteria

```
Eval 1: accuracy >= 0.55 (better than random on paired data)
Eval 2: accuracy >= 0.65 (target — matches optimized scoring formula)
Eval 3: response is exactly "A" or "B" (no hallucinated explanations)
Eval 4: latency < 5s per pair (practical for batch use)
```

### Step 4: Run AutoResearch

```bash
/autoresearch huatuo-quality-prompt --runs 10 --mutations 30
```

AutoResearch mutates: prompt wording, metric subset, formatting, few-shot examples, chain-of-thought structure.

### Step 5: Compare against scoring formula

| Method | Expected PCR | Cost |
|---|---|---|
| Current scoring formula | ~50% | Free (local computation) |
| Optimized scoring formula (HUA-2118) | ~65% (target) | Free (local computation) |
| Optimized LLM prompt (this PRP) | ~70%+ (target) | API cost per pair |

If LLM prompt PCR > optimized formula PCR by ≥ 5 pp: the prompt adds value beyond static metrics alone. If not: static metrics are sufficient, no LLM needed.

### Dependencies

- AutoResearch skill (pinned commit; MIT license — verify before install)
- LLM API access (Claude API or similar)
- BugsInPy annotated data (176+ pairs, already extracted)
- Scipy-optimized scoring formula from HUA-2118 (as comparison baseline)

### Impact

- **New skill:** `~/.claude/skills/huatuo-quality-prompt/SKILL.md`
- **New data:** AutoResearch artifacts in `data/autoresearch/`
- **`.gitignore`:** add `data/autoresearch/`
- **No code changes** to existing modules (prompt is external to codebase)

---

## Open Questions

_All open questions resolved before review._

1. **Why not implement this now?** Prerequisites aren't met: HUA-2118 (scoring optimizer) should run first to establish the scipy-optimized baseline. Without a baseline, we can't measure whether the LLM prompt adds value.

2. **Which LLM?** Deferred to implementation time. Claude (via API) is the natural first choice given the Claude Code environment. The prompt should be model-agnostic — eval criteria don't depend on the specific LLM.

3. **Is AutoResearch mature enough?** Pre-alpha (1 commit). Mitigation: pin commit hash, verify license, have a fallback script. The core algorithm is simple; the skill just automates the loop.

4. **Won't this be expensive?** 10 runs × 30 mutations × 176 pairs × ~500 tokens/pair ≈ 26M tokens. At Claude Haiku rates: ~$7. Acceptable for a one-time optimization.

5. **How does this relate to Phase 3 ML models?** This is a lightweight alternative to training a full model. If the optimized prompt achieves ≥ 70% PCR, it may be "good enough" for dataset curation without a trained model. If not, the prompt results inform feature selection for the model.

---

## Review

- [ ] Reviewer 1 (Codex): score ≥ 9
- [ ] Reviewer 2 (Gemini): score ≥ 9
- [ ] Approved on: —

---

## Change History

| Date | Change | By |
|------|--------|----|
| 2026-03-22 | Initial version — split from HUA-2118 v1 (which was rejected for using AutoResearch on numeric params) | Claude Code |
