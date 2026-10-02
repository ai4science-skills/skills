---
name: szl-unit-invariants
description: "Checks declared SI dimensions, allowlisted unit conversions, expected ranges and fixed pointwise invariants (equal, sum, difference, product, ratio) over selected measurement or simulation columns, flagging incompatible quantities, scale errors of 1000x and broken conservation checks. Use when merging instrument exports with different units, validating simulation output against conservation laws, or when a reviewer asks how unit errors were ruled out. Not an uncertainty-propagation or symbolic tool."
license: Apache-2.0
---

# Unit invariants

A µg column read as mg survives every statistical test and ruins the paper. Declare what each column
is supposed to be and let the helper check dimensions, ranges and the relations that must hold
pointwise. Python 3.9+, stdlib, offline, decimal arithmetic at 50 significant digits.

## Use when

- Combining plate-reader, LC-MS and clinical exports that report the same quantity in different units.
- Checking that mass, energy or charge is conserved row by row in a simulation output.
- A flow rate, dose or concentration column has values 1000x off from the declared range.

## Quick start

```bash
python scripts/run.py assets/example.json --output unit-report.json
```

The invented example (a duration, a length in cm and a speed check) returns
`"status": "PASS_DECLARED_CHECKS"` with each quantity's SI dimension vector, `declared_dimension_match`
and SI-normalized values. Introduce a cm/m mix-up and the report carries `SCALE_MISMATCH` or
`RANGE_VIOLATION` with the exact factor.

## Declaring checks

Select a bounded set of columns; declare unit, SI dimension, expected range and prespecified
invariants. Use decimal strings when precision matters. Read `references/contract.md` for the unit
table, dimension order and operation grammar. Call `szl_audit_unit_invariants(record)` in `kernel.py`
or run the CLI. Inspect dimension failures before interpreting numeric agreement; review range
violations, numerical discrepancies, undefined ratios and flagged factors of at least 1000.
Preserve original values: a corrected declaration is a new audit, not evidence that the original passed.

## What it does not do

Offset units (Celsius), logarithmic units, implicit broadcasting, arbitrary formulas and units absent
from the table are rejected. Success means the declared checks pass on supplied values; observed units,
physical laws and scientific conclusions are not verified, and finite decimal arithmetic does not replace
uncertainty propagation or a symbolic proof. Limits: 1 MiB input, 1000 quantities and invariants,
10,000 samples. Provenance: `references/provenance.md`.
