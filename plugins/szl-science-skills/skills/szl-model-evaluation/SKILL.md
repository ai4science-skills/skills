---
name: szl-model-evaluation
description: "Scores binary predictions (Brier, log loss, ECE, MCE, AUROC, accuracy, reliability bins, per-cohort) or saved categorical outputs joined to retained targets, and audits a multi-run evaluation plan so failed, timed-out, invalid and missing attempts stay in the denominator. Use when the user reports held-out model quality, asks whether a classifier is calibrated, or when a 'best of N runs' number needs its full attempt ledger. Not for regression, survival or multiclass metrics, and it does not run inference."
license: Apache-2.0
---

# Model evaluation with complete denominators

A success-only score is a different number from a whole-plan score. This skill computes both and
keeps every attempt visible. Python 3.10+, stdlib, offline. The calibration metrics are adapted from
the Apache-2.0 [SZL calibration implementation](https://github.com/szl-holdings/szl-calibration/blob/b2e317877abed98e70f9cf6730944a797837faf1/src/szl_calibration/metrics.py).

## Use when

- "Is this diagnostic classifier calibrated, or just accurate?" (ECE/MCE with reliability bins).
- A paper reports accuracy from the three runs that finished and not the two that crashed.
- Saved categorical outputs (triage labels, cell-type calls) need rescoring against retained targets
  instead of trusting stored correctness flags.
- A cohort breakdown is needed (by site, sex, device) without re-running the model.

## Quick start

```bash
python scripts/run.py assets/example.json
python scripts/run.py assets/attempts-example.json
```

The first synthetic fixture returns `"status": "COMPUTED_ON_SUPPLIED_PREDICTIONS"` with
`brier 0.025`, `log_loss 0.164`, `ece 0.15`, `mce 0.2`, `auroc 1.0`, `accuracy 1.0`, a confusion
matrix and five reliability bins. The second routes to the attempt ledger and returns
`"status": "INCOMPLETE_ATTEMPT_LEDGER"`: planned 7, recorded 6, attempted 5, completed 2,
successful 1, planned accuracy 1/7 with every non-success counted as incorrect.

## Three modes, one entry point

Inputs containing `planned_attempts` route to the ledger (`szl_audit_attempts`), inputs with
`records` route to categorical scoring (`szl_evaluate_categories`), everything else routes to
binary scoring (`szl_evaluate_predictions`). Read `references/contracts.md` for field names.

Before interpreting any score, fix the target population, retained labels, split construction
and predeclared threshold and bin count. Keep observed outputs separate from declarations about
model revision, tokenizer, inference settings and training overlap. Single-class AUROC is null.
Repeated row ids are repeated attempts, not independent samples. A retained plan digest detects
changed plan bytes; it does not prove preregistration.

## What it does not do

No provider calls, model loading, downloads, uploads or promotion. It cannot verify model origin,
split independence or status declarations, and never imputes probabilities for missing attempts.
Conditional metrics over successful outputs must not be reported as whole-plan performance.
Agent efficacy and scientific performance remain `NOT_MEASURED`; energy is null without a measurement.
