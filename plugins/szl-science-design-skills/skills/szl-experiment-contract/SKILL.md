---
name: szl-experiment-contract
description: "Draft and check a prospective experiment contract from a research question, comparison, estimand, experimental units, control, falsifier, harm limit and cheapest decisive measurement. Use before a plan is frozen or data are collected; hand off to szl-analysis-plan-audit only after the researcher completes and freezes the separate analysis plan."
license: Apache-2.0
---

# Experiment contract draft

Help a researcher turn an idea into a falsifiable, reviewable **draft**. Ask for missing design fields rather than filling them with invented facts. Identify the independent experimental unit, allocation unit and analysis unit separately; when they differ, ask for a dependence plan. Suggest a cheaper discriminating measurement when appropriate, but keep the researcher's choice and constraints explicit.

Use `references/contract.md` for the bounded input and output schema. The offline helper reports missing fields and a cautious handoff to `szl-analysis-plan-audit`:

```bash
python scripts/run.py assets/example.json
```

The synthetic example returns `DRAFT_READY_FOR_REVIEW`. A null required field or unchecked assumption returns `NEEDS_RESEARCHER_INPUT` with specific questions; the CLI exits 1. Invalid or duplicate-key JSON exits 2. The helper never executes an experiment, looks up references, computes power or p values, or freezes a plan. A complete draft is not preregistered, scientifically validated, or ready for the frozen-plan auditor. The researcher must set the split digest, alpha and family, practical margin, exclusions, stopping/attempt schedule and freeze time in a separate plan before using that auditor. Retain source references as declarations until checked against their originals.

For an evaluation of this skill, compare it with a structured protocol template on independent tasks. Freeze a blind expert actionability rubric, unsupported-claim count, baseline, exclusions and task-family split before a held-out study. The one-topic [forum pilot](https://github.com/szl-holdings/szl-science-forum-corpus) motivated this draft workflow but is not training data or evidence of benefit.
