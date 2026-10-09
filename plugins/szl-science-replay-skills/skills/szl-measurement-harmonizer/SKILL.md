---
name: szl-measurement-harmonizer
description: "Align two to four bounded CSV measurement exports by explicitly declared specimen IDs and affine unit conversions. Hashes each selected file, rejects ambiguous or incomplete mappings, and emits normalized row-level evidence. Use before comparing laboratories, instruments, or studies that name the same specimens differently or report Celsius and Kelvin, or other declared linear units. Offline and standard-library only; does not infer specimen identity, verify a conversion's scientific authority, propagate uncertainty, or judge whether measurements agree."
license: Apache-2.0
---

# Measurement harmonizer

Two labs can report the same specimens under different identifiers and units. Declare the
identifiers, source hashes, and conversion coefficients before comparing values. This skill
reads the selected CSV bytes and emits each original row beside its normalized value. It blocks
the entire normalized table when a file changes or a mapping is incomplete.

## Run the synthetic example

From this skill folder:

```bash
python -B scripts/run.py assets/example.json --root assets --output harmonized-report.json
```

The example aligns two invented specimens across Celsius and Kelvin exports. Expect
`HARMONIZED`, four normalized rows, and equal normalized values for each specimen across
the two sources. Use a fresh output path for every run. The CLI refuses to replace an input,
the manifest, or an existing report.

## Use on real measurements

1. Put two to four distinct, small, two-column UTF-8 CSV exports under one input root. Keep raw files
   unchanged; record their SHA-256 digests.
2. Copy [the manifest example](assets/example.json). Declare every expected canonical ID,
   every source ID mapping, target unit, and each unit's scale and offset. Review these
   declarations with someone who knows the instruments and specimens.
3. Run `scripts/run.py` with that manifest, the input root, and a new output path outside the
   root. Inspect `findings` before using `rows`; a blocked report has no usable rows.
4. Retain the manifest, raw files, output, conversion authority, and any independent review
   with the result. A corrected mapping requires a new run and a new report.

Read [the contract](references/contract.md) for bounds and status meanings.

This does **not** infer identity from names, detect swapped labels, validate the declared
unit conversion against a standard, check instrument calibration, propagate uncertainty,
run a statistical comparison, or establish scientific agreement. Its `HARMONIZED` status means
only that the selected bytes matched the declared hashes and mapped under the declarations.
