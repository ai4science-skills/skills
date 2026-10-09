---
name: szl-rare-disease-evidence-replay
description: Replay pinned synthetic rare-disease evidence snapshots at a fixed UTC cutoff and show source/provenance ablations without diagnostic or model-performance claims. Use for offline evidence-timeline integrity tests, not patient cases or variant ranking.
license: Apache-2.0
---

# Rare-disease evidence replay

Use this CLI-only skill to test whether a **synthetic** evidence timeline is internally
reproducible at a declared UTC cutoff. It reads one exact-byte-pinned synthetic case and
the latest eligible snapshot of each declared source. It never connects to a registry,
downloads data, calls a model, handles credentials, or executes supplied code.

Run from this skill directory (or copy `assets/` to a separate writable directory):

```bash
python -I -B scripts/replay.py --root . --manifest assets/manifest.json --output replay-report.json
```

The output path must be new and relative to `--root`; the runner refuses overwrite.
All example identifiers and records are invented. The manifest pins the raw SHA-256
of the case and each snapshot and declares exactly two distinct source kinds:
`HPO_ANNOTATIONS` and `CLINVAR_ASSERTIONS`. It selects the latest snapshot of each
kind at or before `cutoff_utc`. Future snapshots are not opened. A missing or
ambiguous latest snapshot, changed bytes, or an incomplete latest snapshot yields
`HOLD`; an older complete snapshot is **never** substituted.

Before authoring another synthetic exercise, read the [input and output contract](references/contract.md)
for the exact manifest, case and snapshot fields and the declared-time boundary.

The case contains only synthetic `SYNTH-HP:` feature tokens with a `recorded_at_utc`
and explicit `PRESENT` or `EXCLUDED` state. For each term, the latest state at the
cutoff wins; later case entries are excluded and counted, not backfilled. An absent
term is not an excluded term. If no case feature exists at the cutoff, replay
returns `HOLD`. HPO-shaped rows retain a source release, synthetic
condition/term tokens, a provenance reference, and `ANNOTATED` or
`EXPLICIT_NEGATIVE_ANNOTATION`. The latter is a present annotation row, not a
case feature's `EXCLUDED` state. ClinVar-shaped rows retain distinct versioned
synthetic `VCV` (variant scope), `RCV` (variant-condition scope), and `SCV`
(submitted assertion scope) tokens with opaque `SYNTH-ASSERT:` values. The
runner does not map different tokens to pathogenicity or infer a clinical conflict.
Any selected annotation, record or submission dated after the cutoff or its
snapshot yields `HOLD` rather than silently dropping it.

`DECLARED_ONLY` means these declared rows and links were replayed at the cutoff,
with deterministic leave-one-source and leave-one-provenance views. It is not a
match score or disease ranking. Ablations retain the original condition set even
when one condition loses every row. Every report, including a structurally successful
one, has `readiness: HOLD` and `qualification: NOT_EVALUATED`. A `HOLD` report
has a reason code and no evidence ledger. Exit 0 means only that the bounded
structural replay completed; exit 2 means HOLD or unsafe output. Retain the
manifest, case, selected snapshots and report together. Local hashes are not
signatures, provider authentication or an independent witness.

The fixed schemas reject unknown/free-text patient fields, real accession formats,
variant calls and identifiers outside the synthetic token namespace. They cannot
prove that an operator-supplied declaration is genuinely synthetic. **Do not input
real patient histories, HPO/ClinVar exports, genomic variants, clinical reports,
or identifiable information.** Qualified researchers own rights and interpretation;
this skill performs no diagnosis, treatment advice or clinical validation. HPO
[annotation guidance](https://obophenotype.github.io/human-phenotype-ontology/annotations/phenotype_hpoa/)
and ClinVar [data model](https://www.ncbi.nlm.nih.gov/clinvar/docs/data_model/) /
[identifiers](https://www.ncbi.nlm.nih.gov/clinvar/docs/identifiers/) describe the
real formats; none of their records are bundled here.

The runner uses Python 3.10+ standard library. It caps the manifest at 32 KiB,
case at 16 KiB, each snapshot at 64 KiB, two sources, 32 snapshots, 32 case
feature entries, 100 rows per snapshot, 16 SCVs per RCV and 32 provenance groups.
It rejects traversal, symlink/reparse paths, secret-like path components, duplicate
JSON keys and existing outputs. This is a cooperative local filesystem check, not
a race-safe sandbox. Local tests do not prove Claude Science registration or host
execution; keep those separate as `NOT_VERIFIED`.
