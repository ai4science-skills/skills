# Paired artifact binding contract

Modified 2026-09-30. Original SZL additions, Apache-2.0 under repository LICENSE.
Base source: `szl-holdings/szl-skills` commit
`9668f1571315e93ca2059b9a44f12beef483532d`, paths
`skills/szl-paired-science/{SKILL.md,references/protocol.md,scripts/qualify.py}`.
No third-party implementation, private data or model assets are bundled. The
existing sign-flip procedure is retained; no unmeasured novelty claim is made.

## External freeze boundary

`qualify(plan, *, expected_manifest_sha256=None)` preserves the v1 callable API.
v2 requires the expected digest supplied separately by the scientist from an
independently frozen input/target/corpus/scorer/normalization manifest. The digest
is **not a top-level field controlled by a prediction payload**. CLI callers pass
`--expected-manifest-sha256`. Keep the original lock when investigating a failure.
Refreshing every payload hash cannot pass a changed dataset against that lock.
A user who replaces the trusted digest changes the evaluation being checked;
the helper cannot authenticate the lock, a timestamp or its custody history.

The digest hashes canonical JSON of these four keys: `corpus_sha256`,
`scorer_sha256`, `normalization_sha256`, `case_bindings_sha256`. The last hashes
the list, sorted by `case_id`, of `{case_id, input_sha256, target_sha256}` for all
training and evaluation cases. Canonical JSON uses sorted keys, separators
`,` and `:`, UTF-8, `ensure_ascii=False`, and no nonfinite numbers. Freeze the
manifest before evaluation; do not let prediction artifacts own gold labels.

## v2 input

Use all v1 fields in [protocol.md](protocol.md), schema `szl.paired-science/v2`,
and one additional `bindings` object. Unknown fields are invalid. The complete
experiment is at most 1 MiB and 64 structural JSON levels. Artifact objects have
exactly `{utf8, sha256}`: `utf8` is raw text at most 256 KiB and its lowercase
SHA-256 hashes those exact encoded bytes, including whitespace. `null` artifacts
or text are explicit missing evidence, never a passing readback. Duplicate JSON
keys, duplicate ids, nonfinite numbers and booleans in numerical fields fail.

`bindings` has exactly `schema` (`szl.paired-bindings/v1`), `cases`, `corpus`,
`scorer`, `normalization`, `plan`, and `trials`:

| Field | Contract |
|---|---|
| `cases` | 1–10000 `{id,input,target}` objects covering `train_ids ∪ test_ids` exactly. Each input/target is an artifact. Targets encode one finite JSON number; case bytes are kept outside prediction envelopes. |
| `corpus` | An inert artifact containing exact selected corpus/evidence bytes; computed digest matches declared `dataset_sha256`. It does not establish source truth or permission. |
| `scorer` | An inert JSON artifact: `{schema:"szl.scorer/v1",tasks:[{task_id,metric,loss_unit}]}` covering all tasks. `metric` is `mae` or `mse`; units match task declarations. No scorer code is executed. |
| `normalization` | An inert JSON artifact: `{schema:"szl.normalization/v1",tasks:[{task_id,records:[{case_id,prediction}]}]}`. Each task covers training cases exactly once and excludes test cases. Targets come from the separate case manifest. Its mean MAE/MSE recomputes `training_scale`. |
| `plan` | An inert JSON artifact containing the projection below; its computed raw digest matches `plan_sha256`. The digest does not prove preregistration time. |
| `trials` | Complete `{task_id,trial_id,baseline,treatment,identity_control}` objects, one per declared pair. Each role is a prediction artifact whose raw digest matches the corresponding v1 prediction digest. |

The plan projection has schema `szl.paired-plan/v1`, the exact experiment's
`source_revision`, `input_scope`, `pre_registered`, `independent_pairs`, `alpha`,
`minimum_normalized_improvement`, `identity_control_tolerance`, sorted `train_ids`
and `test_ids`, and `artifact_digests` with the four freeze keys. `tasks` is sorted
by id and includes only `id`, `loss_unit`, `training_scale`, `scale_scope`, sorted
`expected_trial_ids`. `plan_projection()` can construct this inert object; the
trusted freeze digest must still come from the separate source.

Prediction artifact JSON has exactly `schema` (`szl.predictions/v1`), `task_id`,
`trial_id`, `input_sha256`, `target_sha256`, `corpus_sha256`, `scorer_sha256`,
`normalization_sha256`, and `predictions` (one `{case_id,value}` per test case).
Input/target digests hash the sorted list of `{case_id,sha256}` projections for
the actual evaluation cases. Values are finite numbers. Every baseline,
treatment and identity control must bind the same independently frozen cases,
corpus, scorer and normalization, and the intended pair. Identity artifact bytes
match baseline bytes; the envelope has no role field that would prevent equality.

MAE/MSE loss and training scale readback use fixed relative/absolute tolerances
`1e-12`; this is numerical consistency, not a scientific effect threshold. Invalid
structure raises `ProtocolError` (a `ValueError`). Missing evidence, changed
digests, gold substitution, changed evidence text, incompatible scope, or false
loss readback reject the local comparison before statistical inference.

## Output and acceptance

v2 reports `binding_status` as `VERIFIED_INLINE_BYTES`, `DECLARED`, or `MISMATCH`,
with actual projected digests, the expected lock, findings and missing evidence.
Only complete matching binding can enter the preserved v1 inference procedure.
Incomplete/failed binding has `statistical_evaluation: NOT_RUN`, no task scores,
and status `REJECTED_LOCAL_COMPARISON`. CLI exits 0 for a qualified local result,
1 for a rejected comparison, 2 for typed invalid input. No input is modified.

The original synthetic builder `experiment_v2()` in
`tests/test_science_binding.py` and `assets/example-v2.json` exercise a clean toy
comparison. `assets/fixture-lock.json` belongs only to that fixture. Acceptance
cases include changed labels/text/corpus, fully rehashed payloads against an old
lock, missing bytes or lock, false loss/scale, substituted cases, duplicated or
missing trials, held-out normalization, changed scorer/plan, and invalid types.
No model/provider/GPU calls or scientific evaluation are run by these cases.

`consumption_verified` remains false, `source_authenticity` NOT_VERIFIED, and
`scientific_performance` NOT_MEASURED. An envelope self-declares run metadata;
byte consistency cannot establish actual consumption, independence, correctness
of source text, causal validity, answerability, scientific entailment, licensing
or production authority. Independent run/source/plan-timing evidence is required
before a measured improvement claim. Self-declared SUPPORTS or document spans
are not an entailment check. Human approval covers sensitive use and licensing.
