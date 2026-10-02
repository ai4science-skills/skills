# Scoring and complete-attempt contract

## Existing scoring APIs

`szl_evaluate_predictions(probabilities, labels, n_bins=10, threshold=0.5,
groups=None, metadata=None)` retains its existing binary contract: nonempty matched
sequences; finite probabilities in [0,1]; integer 0/1 labels; 1..1000 bins; optional
matched cohort strings. Its digest binds supplied scoring input, not a generating model.

`szl_evaluate_categories(records, held_rows, label_set, metadata=None)` retains its
saved-output join and exact label/state/ordered-evidence scoring. One saved record is
required per retained row. Invalid parsed outputs remain in its denominator. This API
does not infer missing attempt records; use an original attempt ledger for run accounting.

## Attempt ledger

Call `szl_audit_attempts(planned_attempts, attempts, n_bins=10, threshold=0.5,
expected_plan_sha256=None, metadata=None)`.

Each of 1..10000 planned items has exactly `attempt_id`, `row_id`, `label`. Ids use
1..128 ASCII identifier characters (initial alphanumeric; then alphanumeric, `_ . : -`).
Attempt ids are unique. Labels are integer 0/1, and repeated row ids keep the same label.
Each of at most 10000 observations has planned `attempt_id`, matching `row_id`, and:

| status | required payload | attempted | completed | probability scored |
|---|---|---:|---:|---:|
| success | finite `probability` in [0,1] | yes | yes | yes |
| invalid_output | nonempty `reason`, at most 1024 characters | yes | yes | no |
| timeout, failed, aborted | bounded `reason` | yes | no | no |
| unavailable | bounded `reason` | no | no | no |
| missing (inferred) | no observation | no | no | no |

Non-success observations cannot carry a probability; success cannot carry a failure
reason. Unknown fields, duplicate/unplanned observations and changed row bindings are
errors. In particular a supplied `correct` flag is rejected rather than trusted.
Metadata is a finite JSON object bounded at 64 KiB. The CLI additionally rejects
duplicate keys, nonfinite JSON and input above 8 MiB.

Output has a sorted complete ledger and sorted issue codes, every status count, rates,
plan/input digests and explicit binding declarations. `planned_accuracy` has successful
correct classifications as numerator and all planned attempts as denominator, with
`COUNT_NON_SUCCESS_AS_INCORRECT`. `conditional_probability_metrics` is null if no
successful outputs exist. Missing Brier/log-loss/AUROC values are never manufactured.

`plan_sha256` is SHA-256 of UTF-8 compact JSON of the plan sorted by attempt id, with
sorted object keys and `allow_nan=False`. An optional independently retained matching
digest gives `MATCHED_RETAINED_DIGEST`; absence gives `DECLARED_ONLY`. Neither proves
that the plan predates analysis or that its labels/split are scientifically appropriate.

Three planned records with two successful outputs and one timeout report planned=3,
recorded=3, attempted=3, completed=2, successful=2. The same successes with no timeout
record instead report missing=1 and an incomplete ledger; quality denominator stays 3.
Do not turn repeated attempts on one row into confidence intervals assuming independence.

## Acceptance and provenance

`tests/test_science_attempts_replay.py` uses synthetic data to test successful scoring,
timeout/invalid/unavailable/missing accounting, denominator preservation, row binding,
plan digest mismatch, duplicate ids, bad probabilities and deterministic sorting.
Execution evidence belongs in the run report; writing these tests does not establish
they ran. Scientific/agent efficacy is `NOT_MEASURED`.

Inspected base: `szl-holdings/szl-skills` commit
`9668f1571315e93ca2059b9a44f12beef483532d`, paths
`skills/szl-model-evaluation/{kernel.py,SKILL.md,scripts/run.py,assets/example.json}`.
The existing header and root NOTICE retain the Apache-2.0 metric derivation from
`szl-holdings/szl-calibration` commit `b2e317877abed98e70f9cf6730944a797837faf1`,
`src/szl_calibration/metrics.py`. The new ledger, fixtures and tests are original here
under the repository's Apache-2.0 license. No proprietary platform, CC-BY source text,
third-party skill implementation, model weights or dataset rows were imported.
