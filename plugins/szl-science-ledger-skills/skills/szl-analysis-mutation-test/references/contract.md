# Mutation test contract

`generate` input: `{"rows": [object], "label_column": str?, "k": int = 2, "seed": int = 11, "mutations": [name]?}`.
Rows must be objects; numeric columns are those whose non-null values are all int/float (bools excluded).

Plan (`szl.mutation-plan.v1`): `baseline_sha256`, `expected_detection` (mutations that produced bytes
different from the baseline), and per variant `{mutation, status: GENERATED|SKIPPED|NO_OP, detail, sha256, row_count}`.
A SKIPPED variant records why (no label column, no numeric column, fewer than two numeric columns).

`score` input: `{"baseline_flagged": bool?, "variants": {mutation: {"flagged": bool, "check": str?, "variant_sha256": str?}}}`.
If `variant_sha256` is given and differs from the plan's digest, the outcome is NOT_TESTED (wrong file).

Report (`szl.mutation-coverage-report.v1`): `caught`, `missed`, `not_tested`, `coverage` as `caught/applicable`,
status SCORED, BASELINE_FLAGGED or NO_OUTCOMES_RECORDED.
