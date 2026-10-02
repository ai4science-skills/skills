# Reviewer pack contract

Project directory: `project.json` (any of `name`, `project`, `title`, `question` is used as the title) and
`runs/<YYYYMMDDTHHMMSSffffffZ>-<12 hex>/summary.json` as written by szl-science-workbench
(`szl.science-run.v1`: `checks: {id: {type, path, sha256, findings}}`). The newest run is selected by the
UTC timestamp in its directory name. Per-check reports named in the summary are re-hashed and compared
with the recorded `sha256`; `capsule.json` and `report.json` are summarized when present.

Extra reports: paths relative to the project directory; their `schema`, `status`/`readiness` and finding
fields (`issues`, `findings`, `failures`, `mismatch_indexes`, `missing`, `required_failures`,
`counterexample_count`, `invalid_outputs`, `mismatches`, `divergent`) are summarized.

Unresolved = any check with findings, a report digest mismatch or a missing report, plus any extra report
whose status is FAIL, DIVERGENT, MISMATCH, MISSING, RECEIPT_TAMPERED, ERROR or BASELINE_FLAGGED, or that
carries finding fields.

Verdict: NOTHING_TO_REVIEW, REVIEW_REQUIRED, or NO_UNRESOLVED_CHECKED_FINDINGS. `pack_sha256` is the digest of
the pack before rendering.

Aggregate config: `{"scores": {check_id: float in [0,1]}, "weights": {check_id: float >= 0}}`. Weights are
normalized to sum to 1; a zero score with positive weight gives 0.
