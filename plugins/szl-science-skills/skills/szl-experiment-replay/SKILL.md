---
name: szl-experiment-replay
description: "Replays a pinned, bounded CSV column mean against a frozen reference result and writes an explicit match, divergence or incomplete receipt. Use when a researcher needs to rerun a small tabular result offline and distinguish numeric disagreement from changed evidence."
license: Apache-2.0
---

# Experiment replay

Use Python 3.10+ and the standard library to replay one fixed operation on local CSV data. This
executes the skill's built-in `csv_column_mean_v1`; it does not execute a supplied script,
shell command, notebook, plugin or arbitrary Python. It uses no network or credentials.

## Run

From this skill directory, use a writable copy of the synthetic assets or a study root of your own:

```bash
python -I -B scripts/run.py prepare assets/declaration.json --root . --output replay-pin.json
python -I -B scripts/run.py replay replay-pin.json --root . --receipt replay-receipt.json
```

Each output path must be new and relative to `--root`; the runner refuses overwrite. The
declaration names a CSV input, JSON reference result, column and absolute decimal tolerance.
`prepare` freezes the exact input, reference and built-in `kernel.py` hashes. `replay` checks
those hashes before calculating the mean and writes a receipt. `MATCH` means the observed mean
fell within the declared tolerance; `DIVERGED` means it did not. Changed or missing files yield
`INCOMPLETE`; invalid pins yield `REFUSED`. Exit codes: 0 match, 1 divergence, 2 incomplete or
refused. A reference with a different value must be deliberately prepared as a new pin to test
divergence; editing a previously pinned reference yields `INCOMPLETE`.

Retain the pin, receipt and input/reference bytes together. The self-digests catch accidental
changes but are not signatures. Receipts explicitly say `SAME_HOST_LOCAL`, `signed: false`,
`independent_witness: false` and `scientific_claims_verified: false`. The runner does not prove
the experiment design, data collection, author identity or another machine's reproduction.

## Bounds and relationship to other skills

Input CSV: at most 256 KiB, 10,000 rows, 64 columns; reference JSON: at most 4 KiB. Paths are
canonical relative paths under the selected root. Symlinks, junctions, other reparse points,
special files, traversal, credential-like names and existing output files are refused. This is
for a cooperative local filesystem, not an adversarial race-safe sandbox.

Use `szl-reproducibility-capsule` to inventory broader source, environment and analysis plan
files. Its replay declaration remains inert; this skill independently executes only the fixed
CSV mean operation. For publication, arrange independent retention and a separate witness.
