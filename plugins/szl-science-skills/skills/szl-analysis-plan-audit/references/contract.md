# Frozen-plan input and output

Call `szl_audit_analysis_plan(payload)` or `python scripts/run.py input.json`. Exit codes: 0 CONSISTENT_WITH_DECLARED_PLAN; 1 EXPLORATORY; 2 INVALID_INPUT. `--output` exclusively creates a new file. JSON is UTF-8, at most 1 MiB/depth 32, rejects duplicate keys and nonfinite constants. Unknown object fields are invalid. Identifiers are 1–128 letters/digits/period/underscore/hyphen, starting with a letter or digit. Text fields are nonempty, at most 2048 characters. Times are UTC YYYY-MM-DDTHH:MM:SSZ.

Top fields: `schema` szl.analysis-plan-audit.v1, `plan`, `run`, `deviations`.

Plan has `id`, positive integer `version` <=100000, `frozen_at`, `hypotheses`, `families`, `stopping_rule`, `scheduled_attempts`. Run has `plan_id`, `plan_version`, `plan_sha256`, `started_at`, `completed_at`, Boolean `precommit_declared`, `hypotheses`, `families`, `stopping_rule`, `attempts`. Run's declared times must be consistent with freeze/start/completion. These declarations never prove pre-data commitment.

Each hypothesis (1–32, unique `id`) has exactly:

- `id`, nonempty `statement`, `primary_metric` identifier and `direction` LOWER or HIGHER.
- Nonempty `estimand`, `sample_unit` and `group_unit` identifiers. Use the actual independent unit, for example series rather than correlated forecast horizons; the helper checks agreement, not independence.
- `split_sha256` (64 lowercase hexadecimal characters), `alpha` finite >0 and <=0.1, `family` identifier, and finite nonnegative `practical_margin` <=1e12 in the primary metric's own unit.
- `exclusions`: at most 128 unique-id objects with `id` and nonempty `criterion`. These freeze criteria rather than enumerating private data rows.

Each family (1–32, unique `id`) has `id`, `method` BONFERRONI/HOLM/NONE, finite `alpha` >0 and <=0.1, and integer `size` 1–32 equal to its member count. BONFERRONI member alpha equals family alpha/size within 1e-12; HOLM and NONE member alpha equals the family alpha. NONE supports one member only. HOLM means the declared family procedure; this auditor does not run Holm tests or rank p values. Plans using other correction policies require another schema, not guessed equivalents.

Stopping rule has exactly `kind` FIXED_ATTEMPTS and integer `maximum_attempts` 1–256. Scheduled attempts have unique `id`, `hypothesis_id`; schedule count equals maximum attempts and every planned hypothesis has at least one scheduled attempt. Only this fixed-budget plan is supported; no efficacy-based early stopping or adaptive analysis is implemented.

Each supplied attempt has exactly `id`, `hypothesis_id`, `status` SUCCESS/FAILED/ABORTED, `recorded_at`, `result_sha256`, `failure_reason`. A success has a valid declared digest and null failure reason. A failure/abort has a null result digest and nonempty reason. All scheduled ids must occur once, match their hypothesis and have declared time between run start and completion. Extra/missing attempts or exceeding run's declared maximum produce EXPLORATORY. Properly retained failures/aborts alone do not change consistency status. Result bytes are not read: result binding is DECLARED_DIGEST_ONLY.

Each versioned deviation (at most 256) has unique `id` and `path`, `plan_version`, `planned_sha256`, `observed_sha256`, `declared_at`, `reason`. Paths use `/hypotheses/<id>/<field>`, `/families/<id>/<field>` or `/stopping_rule/<field>`. Added/removed hypothesis/family has a presence path `/hypotheses/<id>` or `/families/<id>`; comparison uses true versus null. Values are hashed using `canonical_sha256`: sorted JSON keys, comma/colon separators, ensure_ascii false, UTF-8 and no NaN. Exclusion-list order is part of the contract and changing it is a deviation. Deviations must bind the current frozen plan version and actual changed value hashes; an unchanged path, inconsistent hash/version or timing adds a finding. Every changed path requires an entry. Documented deviations remain exploratory relative to the original fixed plan; the report never retrospectively calls an amended analysis prespecified.

Output schema is szl.analysis-plan-audit-report.v1. It includes status, canonical plan/run hashes, sorted findings and changed-value hashes, scheduled/observed attempt counts and SUCCESS/FAILED/ABORTED totals. No result content is scored. Any finding produces EXPLORATORY, including plan identity/hash/timing conflicts, unproven precommit declaration, changed settings, missing/extra/misbound attempts and invalid deviation provenance. Invalid contracts raise ValueError/CLI INVALID_INPUT instead of emitting a partial clean report. Preregistration remains DECLARED_ONLY even for a consistent plan; statistical inference is NOT_PERFORMED and scientific performance NOT_MEASURED.
