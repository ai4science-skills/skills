---
name: szl-analysis-mutation-test
description: "Mutation testing for a data pipeline's quality checks: generates deliberately corrupted copies of a dataset (duplicated samples, dropped rows, shuffled labels, a x1000 unit error, swapped columns, injected missing values, type confusion) and scores which corruptions the project's own QC caught or missed. Use when the user asks whether their validation would catch a bad merge, a unit mistake or a label mix-up, when hardening a pipeline before a paper, or when a reviewer asks how data errors are detected. Not a data-cleaning tool."
license: Apache-2.0
---

# Analysis mutation test

A QC step that has never seen corrupted data has never been tested. This skill builds the
corrupted variants and keeps score; the pipeline under test is run by you, never by the helper.
Stdlib only, offline.

## Use when

- "Would our checks notice if two plates were accidentally duplicated?"
- A dose column arrives in µg instead of mg once a year and nobody is sure the pipeline would flag it.
- A methods section claims "data were validated" and the reviewer asks against what.
- Before freezing an analysis plan, to list which failure classes are and are not covered.

## Quick start

```bash
python scripts/run.py generate assets/example.json --out-dir variants/
# run your own QC on variants/<mutation>.json and record flagged: true/false per variant
python scripts/run.py score variants/plan.json assets/outcomes-example.json
```

With the synthetic outcomes file the report is `"status": "SCORED"`, `"coverage": "6/10"`,
`"missed": ["drop_rows", "shuffle_labels", "precision_drift", "reorder_rows"]`. Read it as a list
of blind spots: this QC catches unit and schema errors but not a silently dropped sample or a
label permutation. Exit 0 whenever a phase ran; 2 on malformed input.

## Mutation classes

`duplicate_rows`, `drop_rows`, `shuffle_labels` (needs `label_column`), `scale_column` (x1000 on the
first numeric column), `swap_columns`, `inject_missing`, `precision_drift` (+1e-7), `type_confusion`
(numbers become strings), `reorder_rows`, `truncate` (first half only). Each variant file records the
exact change and its SHA-256; the plan file written next to them lists what detection is expected. Generation is deterministic
for a given `seed`.

## Recording outcomes

```json
{"baseline_flagged": false,
 "variants": {"scale_column": {"flagged": true, "check": "dose-range"}, "drop_rows": {"flagged": false, "check": "none"}}}
```

If `baseline_flagged` is true the checks reject the untouched data and the score is reported as
`BASELINE_FLAGGED` instead of a coverage count, because detection numbers would be meaningless.

## What it does not do

It does not execute your pipeline, does not clean or repair data, does not estimate real-world error
rates, and the coverage count is not a quality score. Semantic errors (a plausible but wrong label on
one sample) are outside its reach by design. Details: `references/contract.md`.
