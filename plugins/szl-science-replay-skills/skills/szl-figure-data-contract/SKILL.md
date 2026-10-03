---
name: szl-figure-data-contract
description: "Renders and replays a bounded local CSV-to-SVG scatter or line figure with row IDs, units, numeric caption assertions and byte receipts. Use to inspect a declared figure outside its authoring application and detect dropped, reordered or altered points."
license: Apache-2.0
---

# Figure data contract

Use Python 3.10+ and the standard library. From this skill directory:

```bash
python -I -B scripts/run.py render assets/spec.json --root . --output figure-bundle
python -I -B scripts/run.py verify figure-bundle --root .
```

The specification in `assets/spec.json` names a local UTF-8 CSV, distinct ID/x/y
columns, axis units, scatter or line geometry, and count/minimum/maximum caption
assertions. Decimal observations and extrema are strings. Line points retain CSV
row order; no sorting, aggregation, interpolation or hidden filtering occurs.
The synthetic example uses `assets/data.csv`.

Rendering refuses incorrect caption assertions before writing a bundle. Output
must be a new relative directory with an existing parent under the selected root.
It contains an SVG figure, plotted-data JSON and a receipt with hashes of input,
specification, outputs and this helper. Verification recomputes the declared data,
parses SVG point geometry and visible units/caption, and checks the byte bindings.
Only canonical generated SVG bytes pass; declarations, external stylesheet
instructions, added elements and otherwise equivalent reformattings are refused.
It does not execute a supplied notebook, script or arbitrary transform.

`MATCH` (exit 0) means this declared mapping and numeric caption agree with the
retained bytes; `MISMATCH` (exit 1) means a binding or checked quantity differs;
`UNKNOWN` (exit 2) means inputs are invalid, unsupported, missing or unavailable.
Readable retained inputs with changed byte hashes are `MISMATCH` even if the
changed contents would no longer parse; missing or unreadable files stay `UNKNOWN`.
The verifier shares decimal parsing and coordinate arithmetic with the renderer;
its separate SVG inspection is not an independently authored numerical method.
Keep original source bytes with the bundle so another reviewer can rerun it.

Hashes are unsigned: a person can alter all inputs and create a new internally
consistent receipt. The skill does not establish measurement authenticity,
scientific correctness, independent replication or arbitrary existing figure
pixels. Raw CSV is not copied into the bundle, but plotted coordinates, row IDs
and summary values can disclose study data; review them before sharing.

Bounds: CSV 256 KiB, 10,000 rows, 64 columns; JSON spec 16 KiB; unique safe row IDs;
finite decimals with at most 32 digits within 1e-100 to 1e100; SVG/sidecar reads 2 MiB each. Paths must be
relative POSIX paths. Symlinks, junctions, reparse points, traversal, special files
and credential-like paths are refused. This assumes a cooperative local
filesystem; it is not a race-safe sandbox. No network, credentials or packages
are needed. No RO-Crate conformance, Claude Science registration or measured
agent effectiveness is claimed.

For broader source/environment retention use szl-reproducibility-capsule. For a
figure caption's location in a PDF use szl-paper-evidence-audit. This skill checks
the declared CSV-to-figure mapping, which those checks do not replay.
