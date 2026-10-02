---
name: szl-dataset-readiness
description: "Audits a tabular dataset before training or evaluation for exact duplicate rows across train/test, the same subject, patient, cell line or sensor appearing in both splits, labels observed after the prediction time, and preprocessing fitted on held-out rows, all bound to actual row IDs. Use when the user is about to split data, asks 'is my test set clean', reports suspiciously high held-out accuracy, or a reviewer asks about leakage. Not a data-cleaning or imputation tool; it does not approve scientific suitability or data rights."
license: Apache-2.0
---

# Dataset readiness

Most impossible accuracies come from a test set that already knows the answer. This audit finds
the mechanical versions of that mistake and names the rows involved. Python 3.10+, stdlib, offline.

## Use when

- A patient, mouse, cell line, sensor or template family appears in both train and test.
- Two rows are byte-identical except for the split they landed in.
- A label (diagnosis, failure, churn) was recorded after the moment the prediction would have been made.
- A scaler, imputer or vocabulary was fitted on all rows and then "held-out" rows were scored.

## Quick start

```bash
python scripts/run.py assets/example.json
python scripts/run.py assets/leakage-clean.json
```

The first synthetic table returns `"status": "ISSUES_FOUND"`, `"readiness": "REVIEW"` with
`"issues": ["EXACT_FEATURE_DUPLICATES", "CROSS_SPLIT_FEATURE_LEAKAGE", "CROSS_SPLIT_GROUP_LEAKAGE"]`
and the offending row indexes (`[0, 2]`, one in test, one in train). The second is a clean design and
returns `NO_CHECKED_ISSUES` for every supplied check while readiness stays `REVIEW`.

## Preparing the input

Decide first what one observation is (a sample, a visit, a plate well), where predictions originate
in time, which column identifies the entity that must not straddle splits, and how the split was
designed. Then call `szl_audit_dataset` in `kernel.py` on explicitly bounded rows, or write the JSON
the CLI reads. Use content-defining feature columns that exclude row ids and split names. Add a
`leakage_spec` to check entity, temporal and preprocessing evidence; bind transform fit row ids to the
evidence you actually have, and distinguish when a label became available from when it was observed.
A `TRAIN_ONLY` declaration alone does not establish train-only fitting. Read `references/contract.md`
when preparing that manifest or interpreting missing evidence.

The helper never samples silently, never imputes missing timestamps, and never infers timezone or
column meaning. Metadata records the source revision and license as declared without verifying them.

## What it does not do

`NO_CHECKED_ISSUES` applies only to the supplied checks and selected rows; readiness remains `REVIEW`
until a human decides. Semantic near-duplicates, causal leakage through derived features, label
validity and population suitability are outside its reach and need separate investigation. Digests
are not anonymization. No network, model calls, training, upload or performance claim follows.
