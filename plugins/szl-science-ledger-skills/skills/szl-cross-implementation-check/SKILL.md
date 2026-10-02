---
name: szl-cross-implementation-check
description: "Compares two independent implementations of the same analysis (R vs Python, student vs postdoc, old vs refactored pipeline, paper table vs re-run) quantity by quantity under declared tolerances and reports CONSISTENT / DIVERGENT / INCOMPARABLE. Use when the user wants to confirm a re-implementation reproduces the original numbers, reconcile two sets of results, or check a port before trusting it. Not for deciding which implementation is correct."
license: Apache-2.0
---

# Cross-implementation check

Two result files in, one verdict per quantity out. Both sides declare the digest of the input
they consumed, so "same numbers from different data" is caught as INCOMPARABLE instead of
passing. Stdlib only, offline.

## Use when

- "I rewrote the lme4 model in statsmodels; do I get the same estimates?"
- A student re-derived Table 2 and some p-values look different.
- A refactor touched the pipeline and the team wants proof the outputs did not move.
- Two labs computed the same metric on a shared dataset.

## Quick start

```bash
python scripts/run.py assets/example.json
```

The example compares an R run and a Python run on the same input digest with `rtol 0.01`
(and `rtol 0.5` for `p_value`). Result: `"status": "DIVERGENT"`, 3 consistent, 2 divergent,
1 incomparable:

```
n               CONSISTENT    WITHIN_TOLERANCE
effect.estimate CONSISTENT    WITHIN_TOLERANCE   (0.4213 vs 0.4209)
effect.se       DIVERGENT     EXCEEDS_TOLERANCE  (0.0871 vs 0.0994)
p_value         DIVERGENT     EXCEEDS_TOLERANCE
converged       CONSISTENT    EXACT_COMPARISON
aic             INCOMPARABLE  REPORTED_BY_ONE_SIDE_ONLY
```

That is the typical real finding: the point estimate agrees, the standard error does not, so the
two implementations differ in the variance estimator, not the model. Exit 0 whenever the comparison ran; 2 on malformed input.

## Input

```json
{"a": {"label": "R 4.4", "implementation": "analysis.R", "input_sha256": "<digest>", "results": {...}},
 "b": {"label": "Python", "implementation": "analysis.py", "input_sha256": "<digest>", "results": {...}},
 "tolerance": {"atol": 0.0, "rtol": 0.01},
 "per_quantity_tolerance": {"p_value": {"rtol": 0.5}}}
```

`results` may be nested; keys are flattened to dotted paths. Numbers are compared with
`|a-b| <= max(atol, rtol*max(|a|,|b|))`; strings and booleans must match exactly; anything
reported by one side only, non-finite or non-numeric is INCOMPARABLE. If both sides declare
`input_sha256` and they differ, the overall verdict cannot be CONSISTENT.

## What it does not do

It does not run either implementation, does not know which one is right, and does not pick
tolerances for you: declare them from the precision you actually need, and record why.
Agreement is evidence that two codebases agree on this input, nothing more.
