---
name: szl-multiplicity-audit
description: "Audit a complete, predeclared family of hypothesis tests against a byte-bound results ledger. Compute Holm familywise or Benjamini-Hochberg false-discovery adjusted p-values only when every planned result is present, no undeclared result or extra analysis attempt appears, and the plan digest matches. Use before citing significance across multiple outcomes, model comparisons, screens or subgroups. Offline; no credentials or outside services."
license: Apache-2.0
---

# Multiplicity audit

One attractive p-value can hide a family of unreported tests. This skill reads a declared plan and
a separate results ledger, binds the plan's exact bytes by SHA-256, counts every planned member,
then computes adjusted p-values only for a complete family. It is Python standard library, offline.
It contacts no outside services and expects no credentials.

## Use

1. Create a plan following `references/contract.md` before looking at outcomes. Keep its original
   bytes and an independently trusted timestamp or publication record if preregistration matters.
2. Put every planned hypothesis in the plan, with one result per id in the results ledger. Record
   any other analyses in `extra_attempts`; do not silently select a preferred attempt.
3. Set `plan_sha256` to the SHA-256 of the plan file's exact bytes. Run:

```bash
python scripts/run.py assets/plan.json assets/results.json --output family-report.json
```

The synthetic example has four hypotheses. Holm adjusts the smallest p-value to 0.004 and rejects
only that one at alpha 0.05; the other adjusted p-values are 0.08, 0.06 and 0.08 in plan order.
Changing the plan, omitting a result, or declaring an extra attempt yields `HOLD` and **no adjusted
values**. Exit 0 = complete calculation, 1 = HOLD, 2 = malformed input or I/O error.

## Method boundary

- `holm` controls familywise error under the method's valid-p-value conditions without a
  dependence declaration. It is the conservative default for a declared family.
- `bh` controls a different target, false discovery rate, under its assumptions. The plan must
  explicitly declare `independent` or `positive_regression_dependency` (PRDS on the true-null
  tests); this skill records the assertion but cannot test it. Unknown dependence yields HOLD. Do not substitute BH for Holm
  after seeing the results.
- The report's `reject_at_alpha` is a decision under the selected procedure, **not** proof that a
  scientific hypothesis is true. A digest does not prove a plan was fixed before data inspection.

It does not calculate raw p-values, verify test calibration, detect hidden analyses absent from
both files, establish preregistration, or approve a clinical or scientific claim. See
`references/contract.md` for limits and the underlying statistical sources.
