---
name: szl-model-evaluation
description: Evaluate binary probabilities or saved categorical triage outputs while recording model, data and split evidence separately. Use for scientific classifiers, scored-prediction comparisons, or checking held-out evidence behind a model-quality claim.
license: Apache-2.0
---

# Model evaluation with evidence boundaries

Establish the scientific task, target population and operating threshold. Distinguish trained
weights, adapters, executable software and cards. Record model revision, base/adapter binding,
tokenizer/config, inference settings, dataset revision, split construction and possible
training overlap. A filename or reachable model page does not establish these bindings.

Use actual saved predictions when available. Do not silently replace the selected model.
Paid inference or large downloads are separate actions; the bundled helper scores supplied
predictions only.

Call `szl_evaluate_predictions(probabilities, labels, n_bins, threshold, groups, metadata)`
from `kernel.py`. It supports binary integer labels 0/1 and positive-class probabilities.
Metrics: Brier, clipped log loss, ECE/MCE, tie-aware AUROC, accuracy, confusion counts and
reliability bins. Cohorts use the same settings. Bins compare mean positive probability with
positive frequency, not confidence of the predicted class. Multiclass, regression, survival
and general generative tasks need different metrics.

For saved SZL triage outputs, call `szl_evaluate_categories(records, held_rows, label_set, metadata)`.
It requires one prediction per retained held-out row id, exact target/family matches and a
declared label set. It recomputes label/state/evidence correctness from `parsed`, ignores saved
correctness flags and includes invalid outputs in the denominator. It reports categorical
confusion and exact-match accuracy, never fake binary probabilities. It verifies the target
join to these retained files; it does not authenticate the model that generated the records.
The CLI routes an input with `records` to this evaluator.

Declare thresholds and bins before comparison; separate tuning from final evaluation. Show
denominators. AUROC is null for a single-class cohort, never an invented 0 or 1. Small cohorts
and lack of confidence intervals limit interpretation. The helper cannot authenticate the
prediction/model binding or held-out split; inspect those artifacts separately. No promotion,
readiness certificate or general performance claim follows from this computation.

```bash
python scripts/run.py assets/example.json
```

Input: `probabilities`, `labels`, optional `n_bins`, `threshold`, `groups`, `metadata`.
The example is synthetic, not a result for any SZL model. Attach actual reports and input
digests to the scientist's research memory when persistent evidence is wanted.

Metrics adapt the actual
[SZL calibration implementation](https://github.com/szl-holdings/szl-calibration/blob/b2e317877abed98e70f9cf6730944a797837faf1/src/szl_calibration/metrics.py)
to Claude Science's kernel constraints. Existing SZL models are candidates for task-specific
evaluation, not automatically qualified substitutes.

Outside services/credentials: none offline. Optional metadata lookups contact GitHub/Hugging
Face. Requested inference sends selected inputs to the chosen provider and requires that
provider's credential; do not transmit private data merely to score predictions. Energy
remains null without actual measurement.

Runtime: Python 3.10+; offline; no model weights or inference provider required.
