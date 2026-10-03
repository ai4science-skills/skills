---
name: szl-math-claim-check
description: "Checks a mathematical claim two ways: numerically, by testing declared cases under fixed tolerances and recording counterexamples; and structurally, by auditing a theorem-to-code claim's bindings (exact proposition, domain, assumptions, checker log, custom axioms) without trusting a PROVEN label. Use when a formula, inequality, conservation law or 'we proved that' statement is offered as evidence, when a Lean or Coq result is cited for a runtime, or when a derivation looks too convenient. Not a theorem prover and not a CAS."
license: Apache-2.0
---

# Mathematical claim checking

Write the exact statement, quantifiers, domain and assumptions. Separate definitions, cited
theorems, conjectures, numerical observations and remaining proof obligations, then let the helper
record what the evidence actually covers. Python 3.10+, stdlib, offline.

## Use when

- A manuscript asserts an identity or bound "for all x in [0,1]" and you want cases at zeros,
  boundaries and extreme scales tested under declared tolerances.
- A repository says a property is PROVEN and a runtime relies on it; you need the proposition bytes,
  the checker log and the axiom list bound to that claim rather than a text search for `sorry`.
- Two groups disagree about whether a reported formula holds on the published numbers.

## Quick start

```bash
python scripts/run.py assets/example.json
python scripts/run.py assets/scope-example.json
```

The numerical example tests a deliberately false claim (that a weighted geometric mean always equals
the minimum) and returns `"status": "NUMERICAL_COUNTEREXAMPLE"` with the failing case
`inputs [0.25, 1], lhs 0.5, rhs 0.25` and `proof_discharged: false`. The scope example returns
`"status": "STRUCTURAL_CHECKS_PASSED"` with statement, proposition and log digests and, again,
`proof_discharged: false`: structure passing is not a proof.

## Numerical cases

Use `szl_check_math_cases(claim, cases, relation, atol, rtol)`. Cases supply reviewed `inputs`, `lhs`,
`rhs`; fix tolerances and the tested domain before looking at results. A clean run establishes only
`NO_COUNTEREXAMPLE_IN_TESTED_CASES`. Inspect exact arithmetic and rounding before treating a
discrepancy as a mathematical refutation. The bundled `szl_weighted_geomean` helper accepts axes in
[0,1] and nonnegative weights summing to one; a zero axis with positive weight pins the result to zero.
The report also records that the uniqueness of that aggregator is an open conjecture, so nobody can
cite the demo as a theorem.

## Theorem-to-runtime scope

Read `references/scope-contract.md`. Supply immutable source, toolchain and dependency observations,
the theorem symbol, proposition bytes, the retained checker log and its transitive axiom observations.
`szl_audit_math_scope(contract)` checks bindings, missing assumptions, interval extensions, one-way
claims presented as iff, unfinished proofs, custom axioms and numeric boundary review. It reads
supplied records only and never invokes a prover or evaluates a formula.

## What it does not do

No symbolic proof checking, no arbitrary predicates (named real intervals only), no external service,
model or GPU call. Input is capped at 8 MiB. Failures are retained; unrun evaluation is `NOT_MEASURED`.
Source pins and rights boundaries are in `references/provenance.md`.
