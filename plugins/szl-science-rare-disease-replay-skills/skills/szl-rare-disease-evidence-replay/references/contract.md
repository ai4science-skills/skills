# Synthetic evidence replay contract

This contract describes the offline v1 inputs to `scripts/replay.py`. The bundled
`assets/manifest.json` and related files are complete synthetic examples. All objects
reject extra fields and duplicate JSON keys. Dates are exact UTC seconds in
`YYYY-MM-DDTHH:MM:SSZ` form; file hashes are lowercase SHA-256 of raw bytes.

## Manifest and selection

The manifest has exactly `schema` (`szl.rare-disease-evidence-replay.manifest.v1`),
`data_class` (`SYNTHETIC`), `cutoff_utc`, `case`, and `sources`. `case` has `path`
and `sha256`. `sources` contains exactly two unique `{id, kind, snapshots}`
objects, one kind `HPO_ANNOTATIONS` and one `CLINVAR_ASSERTIONS`. Each snapshot
declaration has `id`, `captured_at_utc`, `release`, `path`, and `sha256`; IDs and
paths must be unique. `release` uses a `SYNTHETIC-` token. Source and snapshot IDs
are lowercase identifier tokens. Paths are slash-separated relative paths beneath
`--root`, without traversal, symlinks/reparse points or secret-like components.

For each source, the runner chooses the unique latest declared snapshot with
`captured_at_utc <= cutoff_utc`. It verifies and opens **only** that snapshot.
Future declarations are counted but their bytes and pins are not checked at this
cutoff. If no snapshot is eligible, latest timestamps tie, the selected bytes
change, or the latest snapshot says `complete: false`, the result is `HOLD`;
there is no fallback to an older complete snapshot. Times and `complete` are
operator declarations, not independently witnessed historical availability.

## Case and selected source snapshots

The pinned case has exactly `schema` (`szl.rare-disease-evidence-replay.case.v1`),
`synthetic: true`, `rights: SYNTHETIC_ONLY`, `case_id`, and `features`. `case_id`
uses `SYNTH-CASE:`; each feature has `term` (`SYNTH-HP:`), `state` (`PRESENT` or
`EXCLUDED`) and `recorded_at_utc`. The latest state per term at or before the
cutoff wins; a tie or no eligible feature yields `HOLD`. Later entries are
counted, not used. No row for a term is not an `EXCLUDED` row.

Each selected snapshot has exactly `schema`
(`szl.rare-disease-evidence-replay.snapshot.v1`), `synthetic: true`,
`rights: SYNTHETIC_ONLY`, `source_id`, `kind`, `release`, `complete`, and the
kind-specific row array. Its source_id, kind and release must match the manifest.

- `HPO_ANNOTATIONS` uses `annotations`: each row has `condition` (`SYNTH-COND:`),
  `term` (`SYNTH-HP:`), `qualifier` (`ANNOTATED` or
  `EXPLICIT_NEGATIVE_ANNOTATION`), `source_ref` (`SYNTH-REF:`), and
  `observed_at_utc`. An explicit negative is a present annotation, not absence
  and not the case feature's `EXCLUDED` state.
- `CLINVAR_ASSERTIONS` uses `records`: each row has `condition`, versioned
  synthetic `vcv` and `rcv`, `observed_at_utc`, and nonempty `submissions`.
  Each submission has distinct versioned synthetic `scv`, opaque
  `assertion_token` (`SYNTH-ASSERT:`), `source_ref`, and `observed_at_utc`.
  VCV, RCV and SCV are separate scopes; assertion tokens are not mapped to
  pathogenicity or interpreted as clinical conflicts.

All selected row and submission times must be no later than both the selected
snapshot capture and cutoff. The manifest is capped at 32 KiB, case at 16 KiB,
each snapshot at 64 KiB, with at most 32 snapshots, 32 case entries, 100 rows
per snapshot, 16 submissions per record, and 32 provenance groups.

## Output and authority

`--output` must be a new relative path under `--root`; no existing file is
overwritten. A valid structural run returns exit 0 with `status: DECLARED_ONLY`,
`readiness: HOLD`, and `qualification: NOT_EVALUATED`. It retains selected source
IDs, releases, capture times and hashes; case states; condition-level rows;
and deterministic leave-one-source/provenance-out views. Ablations retain the
original condition set. A failed run returns exit 2 and a `HOLD` report with
a reason but no evidence ledger. Local hashes prove byte agreement with the
operator-supplied manifest, not authentic source history. Neither output is a
diagnosis, disease ranking, model evaluation or clinical-use qualification.
