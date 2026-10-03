# Dataset leakage evidence contract

Modified 2026-09-30. Original SZL implementation; Apache-2.0 under the repository
LICENSE. Base source: `szl-holdings/szl-skills` commit
`9668f1571315e93ca2059b9a44f12beef483532d`, paths
`skills/szl-dataset-readiness/{kernel.py,SKILL.md,scripts/run.py,assets/example.json}`.
No third-party code, data, model weights or dataset rows are bundled.

`szl_audit_dataset(rows, feature_columns, split_column="split", group_column=None,
metadata=None, *, leakage_spec=None)` retains the existing API and report fields.
Inputs are JSON values, at most 100000 selected rows, 8 MiB canonical evidence,
32 nested levels and 1000000 value nodes. Nonfinite values and unsupported Python
types raise `ValueError`. Feature names are explicit and exclude the split column.
Feature lists are limited to 64 names, entity lists to 32 and split-design lists
to 32, bounding nested work as well as the serialized evidence size.
The CLI accepts JSON only, rejects duplicate keys and nonfinite values, returns 1
for invalid input and 0 for a completed audit, including one finding issues.

The optional `leakage_spec` has schema `szl.dataset-leakage/v1`, a required
`row_id_column`, and these optional sections:

| Section | Exact evidence |
|---|---|
| `entity_columns` | Unique column-name list. Every nonmissing entity value must be a string or integer, excluding booleans. Each column is checked separately so different identifiers cannot hide shared entities. |
| `temporal` | Object with `observation_time_column`, `label_available_at_column`, `prediction_time_column`, `training_splits`, `evaluation_splits`, `split_order`. The three time columns differ; training/evaluation lists are disjoint and the unique order covers both exactly. |
| `expected_transform_ids`, `transforms` | An explicit complete transform list, possibly empty. Each transform has exactly `id`, `fit_row_ids`, `fit_split_ids`, `allowed_fit_splits`. Fit row ids resolve against the selected rows; the observed splits must match the declaration and allowed scope. |

Training fit scope comes from `temporal.training_splits`, or from the optional
top-level `preprocessing_training_splits` list when temporal checks do not apply.
If both are present they must agree. Allowing a held-out split inside a transform
cannot override the declared training boundary. Missing training scope is UNKNOWN
for a nonempty transform list. Nonmissing row split values must be strings.

Read time fields as aware ISO 8601 datetimes, including `Z` or an explicit offset.
Local times, date-only values, invalid timestamps and missing values are unknown
evidence. Normalize offsets to UTC before ordering. A timestamp whose UTC normalization
falls outside the representable datetime range also remains UNKNOWN, with diagnostic
`MISSING_AMBIGUOUS_OR_OUT_OF_RANGE_TIME`; normalization never supplies a substitute time.
Reject duplicate row ids.

Temporal findings identify: observations after their prediction time; training
labels unavailable at the earliest held-out prediction origin; and overlapping
or reversed observation times under the declared strict split order. Held-out
labels may become available after prediction, as they commonly do in forecasting.
The strict split-order rule is appropriate for forward temporal evaluation; omit
the temporal section and report UNKNOWN for designs where it is inappropriate.
This helper does not infer a forecast horizon or causal availability from names.

`leakage_checks` contains `entity`, `temporal`, and `preprocessing`, each with
`status`, deterministic `findings`, and `missing_evidence`. A supplied section
reports `ISSUES_FOUND`, `UNKNOWN`, or `NO_CHECKED_ISSUES`; legacy calls without a
spec report `NOT_CHECKED`. A finding and missing evidence can coexist: retain both.
Incomplete supplied evidence adds `LEAKAGE_EVIDENCE_INCOMPLETE` to `issues`.
No missing evidence becomes a passing check. An absent fit row is unknown even if
the transform declares TRAIN_ONLY. Compare complete observed and declared split
sets only after every fit row and its split resolves. A known observed split
outside the declaration or training boundary remains a finding even when another
fit row is missing; retain the missing evidence alongside it. Input rows are never
modified or sampled.

Reports contain row indexes and hashed entities, not original records. Hashes do
not anonymize values. Fit manifests bind the selected evidence, not actual process
execution; source and license metadata remain declarations. Readiness always
stays REVIEW and scientific suitability stays NOT_ASSESSED. Semantic duplicates,
target leakage through feature generation, distribution shift, omitted transforms,
and misleading declared column semantics need independent review. Sample results
apply only to the selected sample. Scientific/behavioral performance is NOT_MEASURED.

Acceptance cases are original synthetic rows in `assets/leakage-clean.json` and
`tests/test_science_binding.py`: clean design, entity reuse, future observation,
unavailable training labels, reversed split order, held-out transform fitting,
unresolved fit rows, ambiguous time, duplicate ids, and invalid typed values.
