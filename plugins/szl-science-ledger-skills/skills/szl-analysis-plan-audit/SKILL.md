---
name: szl-analysis-plan-audit
description: "Compares a frozen analysis plan (primary metric and direction, estimand, sampling and group units, split digest, multiplicity allocation, practical margin, exclusions, fixed attempt schedule) with a run manifest and a versioned deviation log, and reports whether the run followed the plan or became exploratory. Use when a study was preregistered or an analysis plan was frozen before data access, when a reviewer asks about deviations, or when the user wants to know if a result is still confirmatory. Not a statistics engine; it computes no p value or power."
license: Apache-2.0
---

# Analysis plan audit

The difference between confirmatory and exploratory is whether the analysis that ran is the analysis
that was declared. This helper diffs the two, setting by setting, and keeps failed and aborted
attempts in the ledger. Python 3.9+, stdlib, offline.

## Use when

- A preregistered endpoint was swapped for a secondary one that reached significance.
- The exclusion criteria in the paper differ from the frozen plan.
- Three attempts were scheduled, one failed, and the report mentions only the successes.

## Quick start

```bash
python scripts/run.py assets/example.json
```

The synthetic plan with a retained failed attempt returns `"status": "CONSISTENT_WITH_DECLARED_PLAN"`,
plan and run digests, `attempt_counts {"SUCCESS": 1, "FAILED": 1, "ABORTED": 0}`,
`preregistration: "DECLARED_ONLY"` and `statistical_inference: "NOT_PERFORMED"`. Change a setting after
run start and the amended status becomes `EXPLORATORY` with `DEVIATION_AFTER_RUN_START`.

## Preparing the audit

Read `references/contract.md`, retain the original frozen plan, and run the helper on the plan, run
manifest and deviation log. It computes canonical plan and run digests and compares each declared
setting by hypothesis or family id. Treat any deviation or incomplete attempt as `EXPLORATORY`
relative to the frozen plan, documented amendments included; log plan version, changed path, old and
new value hashes, reason and declared time, and keep the fixed original rather than rewriting it. A
result digest names a declared artifact; use szl-paired-science or szl-model-evaluation to check bytes
or recompute metrics.

## What it does not do

Never supplies a p value, power or efficacy conclusion, chooses hypotheses, certifies causality, trains
a model, calls a provider or uploads data. Precommit declarations, timestamps and hashes cannot prove
that registration preceded access to outcome data. Only fixed-attempt stopping is supported; sequential
or adaptive designs need a different explicit contract. Limits: 1 MiB input, 32 hypotheses or families,
256 scheduled attempts. Provenance: `references/provenance.md`.
