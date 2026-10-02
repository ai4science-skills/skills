---
name: szl-artifact-lineage
description: "Audits the provenance chain of a result: every source, intermediate and output artifact as a versioned id, each transformation's required inputs and stages, producer uniqueness, and whether the digest a step consumed is the digest its parent actually produced, against independently read-back digests. Use when a figure or table must be traced to raw data, when a pipeline rerun silently used a newer input, or when a reviewer asks which version of the data produced which result. Not a workflow engine; it executes nothing."
license: Apache-2.0
---

# Artifact lineage

Raw reads became a count matrix became a normalized matrix became Figure 3. Lineage asks whether
each step consumed exactly the bytes the previous step produced, with no version substituted along
the way. Python 3.9+, stdlib, offline; it reads no artifact files and runs no transformations.

## Use when

- A reviewer asks which raw data version is behind a published table.
- A rerun produced a different figure and nobody is sure which intermediate changed.
- Two pipelines claim to share an input; their declared digests should match.

## Quick start

```bash
python scripts/run.py assets/example.json --output lineage-report.json
```

The synthetic manifest (raw -> normalize -> summarize) returns
`"status": "CONTINUITY_ON_SUPPLIED_DIGESTS"` with stage order `["normalize", "summarize"]`, three
artifacts observed as `MATCH` and `authentic: false`. Substitute a parent digest and the status becomes
`REVIEW_REQUIRED` with `PARENT_DIGEST_MISMATCH`; omit a readback and the artifact is `INPUT_NOT_OBSERVED`.

## Building the manifest

Read `references/contract.md`. Preserve each source, intermediate and result as a separate versioned id;
record every required stage and input, consumed and produced digests, and exact code/config digest
pins. A descriptive operation is data, never a command to run. Obtain readback digests independently
for the selected artifacts and place them in `observed_digests`; ids, filenames, timestamps or an absent
observation never count as matching bytes. Call `szl_audit_lineage(manifest)` in `kernel.py`.

## What it does not do

A clean result means continuity on the supplied digests. It does not establish that the declared
transform actually ran, that a code pin was checked, that an unsigned record is authentic, or that the
result is scientifically correct. Supplied readbacks are caller assertions; use a separately trusted
retained record for adversarial integrity. Limits: 1 MiB input, 1000 artifacts and stages, 10,000 IO
entries. Provenance: `references/provenance.md`.
