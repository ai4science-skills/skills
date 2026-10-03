# Paired comparison protocol

Modified 2026-09-30. This reference preserves the legacy v1 inference contract.
For evidence-bound v2 use [binding-contract.md](binding-contract.md) first. v1
retains its historical qualification status with `binding_status: DECLARED`;
without actual bytes and a separate frozen lock that status is declaration-only.

The input is one UTF-8 JSON object, at most 1 MiB and 64 structural nesting levels, with schema `szl.paired-science/v1`. Duplicate object keys, NaN, and infinity are invalid. Brackets inside quoted strings do not count as structural nesting. Run:

```
python skills/szl-paired-science/scripts/qualify.py experiment.json
```

Exit status 0 means `QUALIFIED_LOCAL_COMPARISON`, 1 means `REJECTED_LOCAL_COMPARISON`, and 2 means `INVALID_INPUT`. The report identifies the exact input bytes and helper bytes using SHA-256. It does not independently verify the declared plan or source commits.

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema` | `szl.paired-science/v1` |
| `source_revision` | Exact 40-character lowercase Git commit |
| `dataset_sha256`, `plan_sha256` | 64-character lowercase SHA-256 declarations |
| `input_scope` | `SYNTHETIC`, `EXTERNAL`, or `MIXED` |
| `pre_registered` | Boolean declaration that the plan preceded evaluation |
| `independent_pairs` | Boolean declaration that sign-flip units are independent; correlated horizons from one series do not establish this |
| `alpha` | Family error threshold, greater than 0 and at most 0.1 |
| `minimum_normalized_improvement` | Nonnegative minimum effect fixed in the plan |
| `identity_control_tolerance` | Nonnegative dimensionless tolerance fixed in the plan |
| `train_ids`, `test_ids` | Nonempty disjoint lists of unique identifiers |
| `tasks` | 1 to 8 task objects |

Each task has `id`, `loss_unit`, `training_scale`, `scale_scope` (must be `TRAIN_ONLY`), `expected_trial_ids`, and `trials`. The scale is a positive finite training-only reference loss, such as the training naive forecast MAE. Every expected trial must be present exactly once; list 3 to 16 independent trials per task. Each trial has `id`, nonnegative finite `baseline_loss`, `treatment_loss`, `identity_control_loss`, and three SHA-256 declarations: `baseline_predictions_sha256`, `treatment_predictions_sha256`, `identity_control_predictions_sha256`.

For pair i in task t, the normalized effect is `(baseline_loss - treatment_loss) / training_scale`. A positive effect favors treatment. The exact one-sided sign-flip p value counts all `2^n` sign assignments whose mean is at least the observed mean, including ties. This test assumes the paired differences are exchangeable under the null and pairs are independent; declarations alone do not validate those assumptions. Each task's p value is multiplied by the task count (Bonferroni correction). A task qualifies only when its mean effect is strictly positive, at least the declared minimum, and its corrected p value is no greater than alpha. All tasks must qualify; selection of only favorable tasks is not allowed.

The identity control must declare the same prediction hash as its baseline, and every normalized control/baseline loss difference must be within tolerance. This catches mismatched scoring, pairing errors, or a changed control. It cannot detect a dishonest hash declaration without the underlying prediction bytes.

For mixed units, retain per-task normalized results; the report deliberately provides no raw cross-task loss average. Hash the original data and plan files before filling their identifiers. Record measured wall time and worker memory in separate resource evidence; a parent launcher or an estimate is not worker memory.
