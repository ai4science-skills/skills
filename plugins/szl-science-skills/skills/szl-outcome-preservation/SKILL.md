---
name: szl-outcome-preservation
description: "Audit an optimization's complete predeclared case cohort for numerical agreement, scientific metric drift and downstream decision changes in exact, fast or big mode. Withhold speed and memory ratios when any case is missing, fails, silently falls back or changes an outcome. Use after model or kernel optimization, precision changes or implementation replacement, especially when small tensor errors can change a scientific conclusion. Offline, bounded, standard library only; no credentials."
license: Apache-2.0
---

# Preserve scientific outcomes after optimization

Run `python scripts/run.py assets/example.json`. The synthetic example stays
inside the numeric tolerance but crosses the scientific threshold. Expect
`REGRESSION_OR_GAP`, `SCIENTIFIC_DECISION_CHANGED` and exit 1; speedup is withheld.

Freeze case ids, tolerances, metric, threshold operator (`ge` or `le`), acceptable
drift and mode before collection. Retain missing/error cases and actual mode
activation; stock fallback cannot count as acceleration.

Schema: `szl.outcome-preservation.v1`; [the example](assets/example.json) shows all
fields. Declare full immutable reference and candidate revisions. Successful
cases have flat finite outputs and a metric from the researcher's declared
method. Exact mode requires equal supplied byte digests and numbers; these are
declarations, not byte readbacks. Fast and big enforce tolerances and decisions.

Timings require three positive samples and matching hardware, dtype, input hash,
warmup, synchronization and measurement method. Memory ratios also require a
declared memory method; peak memory is in bytes. Failure suppresses all ratios.
Do not quote a surviving subset as the full cohort's speedup.

Exit 0: preserved supplied cohort; 1: regression/gap; 2: malformed input. `kernel.py` exports
`szl_outcome_preservation(record)` for a reviewed workflow.

Workbench check type: `outcome-preservation`. Its retained capsule and anatomy
bind inputs and invalidate dependent claims after change. This does not run
models, measure GPUs, authenticate evidence, establish generalization or prove
correctness. Judge the metric with the scientist. Lambda is Conjecture 1 (OPEN).

External services: none. Credentials: none. Dependencies: Python standard library.
