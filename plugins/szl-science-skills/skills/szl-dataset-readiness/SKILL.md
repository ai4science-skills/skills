---
name: szl-dataset-readiness
description: Inspect scientific tables for missing fields, exact duplicates, cross-split feature or subject leakage, and declared provenance and reuse terms. Use before training, evaluation, dataset sharing or admission into a research second brain.
license: Apache-2.0
---

# Dataset readiness

Establish the scientific task, observation unit, labels, subject grouping and split design.
Record immutable source revision, source locator, collection description, consent/access
conditions and stated reuse terms. License metadata alone does not establish permission to
reuse personal data or every upstream item.

Call `szl_audit_dataset` from `kernel.py` on selected rows with explicit `feature_columns`,
`split_column`, optional `group_column`, and `metadata`. Choose identity-defining content;
exclude row ids and split names so copies across splits can be detected. Use subject or
experiment ids as the group column when those units must stay together.

The helper detects exact feature duplicates, subject overlap, missing selected values,
inconsistent row keys and undeclared provenance/reuse metadata. It reports counts, indexes
and digests rather than copied records. Hashes are not anonymization. NO_CHECKED_ISSUES means
only these checks found nothing; readiness stays REVIEW and suitability is NOT_ASSESSED.

Also inspect task-relevant label validity, distribution shift, collection bias, batch effects,
temporal leakage and semantic near-duplicates with appropriate tools. State what was not
checked. Sampling is a sample audit, not a full-dataset result. Retain original row ids when
explaining findings to the scientist; never silently sample.

```bash
python scripts/run.py assets/example.json
```

Input: `rows`, `feature_columns`, optional `split_column`, `group_column`, `metadata`.
Convert selected local CSV/Parquet into a bounded table with established local tools.
The synthetic example intentionally duplicates train/test features and a subject.

Useful SZL inputs:
[formula registry](https://huggingface.co/datasets/SZLHOLDINGS/canonical-formulas-v1/tree/99c45c0989676f9a842a707ab5af60f1e2de99ce),
[Lean theorem tree](https://huggingface.co/datasets/SZLHOLDINGS/lean-theorem-tree/tree/8283cc8b75a54142016c8ac7fac5695903a9e6ba),
[receipts benchmark](https://huggingface.co/datasets/SZLHOLDINGS/governed-receipts-bench/tree/9e8a4921740f310d144012e27e3bb0cb34e733af).
Inspect actual cards and file schemas first. The
[second-brain dataset](https://huggingface.co/datasets/SZLHOLDINGS/szl-second-brain-inrepo/tree/c9823ec107fc1fd4df6166c4ad0a37c776ee7e64)
declares license other; keep it an optional inspection source rather than bundling it.

Outside services: none bundled. Optional Hub/GitHub retrieval sends repo/revision identifiers;
private sources require existing credentials. No automatic upload, training admission,
personal-data export or universal approval follows from the checks.

Runtime: Python 3.10+; stdlib; offline JSON tables up to 100000 rows.
