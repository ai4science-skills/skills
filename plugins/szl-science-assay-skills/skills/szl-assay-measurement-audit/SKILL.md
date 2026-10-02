---
name: szl-assay-measurement-audit
description: "Audits one declared increasing linear laboratory assay run before reporting sample concentrations: separately identified blank and QC wells, calibration residuals and range, unique sample/well IDs, dilution factors, and result-specific uncertainty disclosures. Use when a researcher asks whether a plate's numeric results passed its own prespecified controls, or when a reviewer needs a per-sample HOLD reason. Offline, stdlib-only, synthetic examples. Not method validation, metrological traceability certification, or clinical qualification."
license: Apache-2.0
---

# Assay measurement audit

Run this only on a researcher-specified, increasing **unweighted linear** signal-versus-concentration assay. It checks the run against its own declared limits; it does not choose limits, validate a method or certify a measurement. Require the researcher to identify the method and standard lot, supply separately identified blank and at least two QC wells, and provide nonidentifying sample IDs. Well IDs alone do not verify physical independence. All concentrations and expanded uncertainties must already use the declared `concentration_unit`; no conversion is performed. Expanded uncertainty must be declared for the final dilution-corrected concentration, with the dilution contribution explicitly affirmed when the factor exceeds one. For dimensional conversions or numerical invariants, use the separate `szl-unit-invariants` skill.

## Use

From this skill's directory, run:

```bash
python -B scripts/run.py assets/example.json
python -B scripts/run.py assets/control-failure.json
```

The first invented plate returns `PASS_DECLARED_CHECKS`, concentrations `3` and `2` mg/L, and exit 0. The second has an intentionally wrong QC and returns `FAIL`, with every sample on `HOLD`, no released concentration, and exit 1. Exit 2 means malformed input or execution error. To retain a receipt without replacing an existing file, add the `--output` option followed by a new JSON path; the report binds the exact input bytes by SHA-256.

Read [the contract](references/contract.md) when preparing a new JSON run or interpreting a finding. The kernel can also be called as `szl_audit_assay_measurement(record)` from `kernel.py`. Use [the provenance note](references/provenance.md) when evaluating the method and rights boundaries.

## Interpretation

- `PASS_DECLARED_CHECKS` means only that supplied blank, standard residuals and QC values met the supplied thresholds, sample signals were within the declared calibration/quantification range, and each sample included an expanded-uncertainty and coverage-factor declaration. It is not scientific or clinical approval.
- `HOLD` means required provenance, sample range or uncertainty disclosure is missing/incompatible; no concentration is returned for that sample.
- `FAIL` means a measured control or calibration check failed. All sample concentrations are withheld for that run even if an individual sample signal appears in range.

The tool never uploads data, calls a model, infers a detection/quantification limit, verifies lot identity, propagates uncertainty, checks sample handling or decides whether declared tolerances are fit for purpose. Reported Decimal strings preserve calculation values for machine review; their digits are not a claim of measurement precision. A digest does not authenticate a file. Actual patient identifiers and regulated data should not be placed in the example or an unreviewed environment; submitted IDs appear in the report. More complex curves, weighted fits, decreasing-response assays and multiple batches require a different reviewed method, not a permissive fallback here.
