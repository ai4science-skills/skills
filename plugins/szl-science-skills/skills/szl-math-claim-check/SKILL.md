---
name: szl-math-claim-check
description: Turn a mathematical claim into explicit assumptions, numerical checks and proof obligations. Use for conjectures, invariant tests, formula validation, counterexample searches, or distinguishing Lean-checked results from numerical observations.
license: Apache-2.0
---

# Mathematical claim checking

Write the exact statement, quantifiers, domain, units and assumptions before testing.
Separate definitions, assumptions, cited theorems, conjectures and proof obligations.
Prefer a small falsifying example to many successful random samples.

- Inspect the actual formula and its domain. Include zeros, boundaries, extreme scales and
  zero weights when permitted. Fix tolerances before the run.
- Derive or execute the calculation in a reviewed local implementation. Cases contain
  `inputs`, `lhs` and `rhs`. Call `szl_check_math_cases` from `kernel.py` with an explicit
  equal, le or ge relation. Do not eval a formula string from a paper or dataset.
- Inspect rounding, units and domain membership before interpreting an apparent failure.
  Use rational or high-precision arithmetic where useful. A numerical discrepancy is not
  automatically an exact mathematical refutation.
- For Lean, inspect the pinned project, toolchain and dependency lock. Run the relevant
  target if available; inspect sorry, admit and the theorem's assumptions, including
  `#print axioms`. Retain command, exit status and revision. A repository's PROVEN label
  does not replace those observations.

`szl_weighted_geomean(axes, weights)` is a strict [0,1] numerical helper. A zero-valued axis
with positive weight pins the aggregate to zero; a zero weight ignores its axis. This differs
deliberately from older SZL gates that veto every zero axis regardless of weight; never
silently substitute it into a production gate. Lambda uniqueness remains **Conjecture 1 (OPEN)**.
NO_COUNTEREXAMPLE_IN_TESTED_CASES is not a theorem or proof of uniqueness.

Return the statement, assumptions, source revision, tested domain, failures with inputs,
and remaining proof obligations.

```bash
python scripts/run.py assets/example.json
```

Input supplies `claim`, `cases`, optional `relation`, `atol`, `rtol`. The example tests the
false statement that the geometric mean always equals the minimum.

SZL anchors: [formula source](https://github.com/szl-holdings/szl-formulas/tree/65c800b59249f27559de575bc66f5054fa585fa5),
[Lean source](https://github.com/szl-holdings/lutar-lean/tree/ff4bfecbf6585677f75684c72dd4014c78135366),
[formula dataset](https://huggingface.co/datasets/SZLHOLDINGS/canonical-formulas-v1/tree/99c45c0989676f9a842a707ab5af60f1e2de99ce).
The helper does not run those projects automatically or certify proof status.
Outside services: none offline. Optional source retrieval sends identifiers to GitHub or
Hugging Face; only private sources require credentials.

Runtime: Python 3.10+ offline; Lean is optional and must already be available for formal checking.
